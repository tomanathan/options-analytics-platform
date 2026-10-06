"""Local Iceberg catalog on the standard library's ``sqlite3``, SqlCatalog-compatible.

Why this exists: pyiceberg's own ``SqlCatalog`` is built on SQLAlchemy 2.x, and
``apache-airflow==2.11.2`` pins SQLAlchemy below 2.0, so the two cannot be installed in the
same environment (the Airflow image, or the project's single uv environment). ADR 0005
records the decision. This catalog keeps the local stack working without SQLAlchemy by
talking to SQLite directly.

It stores its state in exactly the two tables pyiceberg's ``SqlCatalog`` uses
(``iceberg_tables`` and ``iceberg_namespace_properties``, with the same column names and the
v1 ``iceberg_type`` column), so a catalog file written here opens unchanged with
``SqlCatalog`` wherever SQLAlchemy 2 is available, and the other way round.

Scope is deliberately small: namespaces (create, list, drop, load and update properties) and
tables (create, register, load, list, drop, rename, commit). Views are not supported.
Commits are optimistic: the row is updated only if its ``metadata_location`` is still the one
the commit was based on; otherwise ``CommitFailedException`` is raised and the caller retries
against the refreshed table.

The SQLite file and the table metadata files are this module's I/O. Every operation opens
its own short-lived connection, so the catalog is safe to use from several processes (for
example concurrent Airflow tasks); SQLite serialises the writes.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, override

from pyiceberg.catalog import (
    METADATA_LOCATION,
    Catalog,
    MetastoreCatalog,
    PropertiesUpdateSummary,
)
from pyiceberg.exceptions import (
    CommitFailedException,
    NamespaceAlreadyExistsError,
    NamespaceNotEmptyError,
    NoSuchNamespaceError,
    NoSuchTableError,
    TableAlreadyExistsError,
)
from pyiceberg.io import load_file_io
from pyiceberg.partitioning import UNPARTITIONED_PARTITION_SPEC, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.serializers import FromInputFile
from pyiceberg.table import CommitTableResponse, Table, TableProperties
from pyiceberg.table.locations import load_location_provider
from pyiceberg.table.metadata import TableMetadata, new_table_metadata
from pyiceberg.table.sorting import UNSORTED_SORT_ORDER, SortOrder
from pyiceberg.table.update import TableRequirement, TableUpdate
from pyiceberg.typedef import EMPTY_DICT, Identifier, Properties
from pyiceberg.view import View
from pyiceberg.view.metadata import ViewVersion

if TYPE_CHECKING:
    import pyarrow as pa

SQLITE_URI_PREFIX = "sqlite:///"
"""URI scheme accepted for the catalog database, as in SQLAlchemy: ``sqlite:///<path>``."""

ICEBERG_TABLE_TYPE = "TABLE"
"""Value of ``iceberg_type`` for tables, as written by pyiceberg's SqlCatalog (schema v1)."""

NAMESPACE_MINIMAL_PROPERTIES: dict[str, str] = {"exists": "true"}
"""Property row written for a namespace created without properties, as SqlCatalog does."""

CREATE_TABLES_SQL: tuple[str, str] = (
    "CREATE TABLE IF NOT EXISTS iceberg_tables ("
    " catalog_name VARCHAR(255) NOT NULL,"
    " table_namespace VARCHAR(255) NOT NULL,"
    " table_name VARCHAR(255) NOT NULL,"
    " metadata_location VARCHAR(1000),"
    " previous_metadata_location VARCHAR(1000),"
    " iceberg_type VARCHAR(5),"
    " PRIMARY KEY (catalog_name, table_namespace, table_name))",
    "CREATE TABLE IF NOT EXISTS iceberg_namespace_properties ("
    " catalog_name VARCHAR(255) NOT NULL,"
    " namespace VARCHAR(255) NOT NULL,"
    " property_key VARCHAR(255) NOT NULL,"
    " property_value VARCHAR(1000) NOT NULL,"
    " PRIMARY KEY (catalog_name, namespace, property_key))",
)
"""DDL of the two catalog tables, matching pyiceberg SqlCatalog's v1 schema."""

_TABLE_ROW_FILTER = (
    "catalog_name = ? AND table_namespace = ? AND table_name = ?"
    " AND (iceberg_type = 'TABLE' OR iceberg_type IS NULL)"
)


def sqlite_path(uri: str) -> Path:
    """Return the database file path of a ``sqlite:///`` URI.

    Args:
        uri: ``sqlite:///relative/path.db`` or ``sqlite:////absolute/path.db``.

    Returns:
        The path; relative paths are relative to the working directory.

    Raises:
        ValueError: If the URI is not a ``sqlite:///`` file URI (in-memory databases are not
            supported because every operation opens a new connection).
    """
    if not uri.startswith(SQLITE_URI_PREFIX):
        raise ValueError(f"expected a sqlite:/// URI, got {uri!r}")
    path = uri.removeprefix(SQLITE_URI_PREFIX)
    if not path or path == ":memory:":
        raise ValueError(f"an on-disk SQLite file is required, got {uri!r}")
    return Path(path)


def _commit_response(metadata: TableMetadata, metadata_location: str) -> CommitTableResponse:
    """Build a commit response; pydantic accepts the field name as well as its alias."""
    return CommitTableResponse(metadata=metadata, metadata_location=metadata_location)  # type: ignore[call-arg]


class LocalCatalog(MetastoreCatalog):
    """Iceberg catalog stored in a SQLite file through ``sqlite3``.

    Args:
        name: Catalog name, stored in every row's ``catalog_name``.
        **properties: Catalog properties. ``uri`` (a ``sqlite:///`` URI) is required;
            ``warehouse`` (for example ``file:///abs/warehouse``) is the default root for new
            tables.

    Raises:
        ValueError: If ``uri`` is missing or not a ``sqlite:///`` file URI.
    """

    def __init__(self, name: str, **properties: str) -> None:
        """Open (and if needed create) the catalog tables in the SQLite file."""
        super().__init__(name, **properties)
        uri = self.properties.get("uri")
        if not uri:
            raise ValueError("LocalCatalog needs a 'uri' property")
        self.path = sqlite_path(uri)
        with self._connect() as conn:
            for statement in CREATE_TABLES_SQL:
                conn.execute(statement)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection inside one transaction: commit on success, roll back on error."""
        with closing(sqlite3.connect(self.path, timeout=30)) as conn, conn:
            yield conn

    def _table_row(self, namespace: str, table_name: str) -> tuple[str, str | None] | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT metadata_location, previous_metadata_location FROM iceberg_tables"
                f" WHERE {_TABLE_ROW_FILTER}",
                (self.name, namespace, table_name),
            ).fetchone()
        if row is None:
            return None
        return row[0], row[1]

    def _insert_table_row(self, namespace: str, table_name: str, metadata_location: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO iceberg_tables (catalog_name, table_namespace, table_name,"
                    " metadata_location, previous_metadata_location, iceberg_type)"
                    " VALUES (?, ?, ?, ?, NULL, ?)",
                    (self.name, namespace, table_name, metadata_location, ICEBERG_TABLE_TYPE),
                )
        except sqlite3.IntegrityError as e:
            raise TableAlreadyExistsError(f"Table {namespace}.{table_name} already exists") from e

    @staticmethod
    def _split(identifier: str | Identifier) -> tuple[str, str]:
        namespace = Catalog.namespace_to_string(Catalog.namespace_from(identifier))
        return namespace, Catalog.table_name_from(identifier)

    @override
    def create_table(
        self,
        identifier: str | Identifier,
        schema: "Schema | pa.Schema",
        location: str | None = None,
        partition_spec: PartitionSpec = UNPARTITIONED_PARTITION_SPEC,
        sort_order: SortOrder = UNSORTED_SORT_ORDER,
        properties: Properties = EMPTY_DICT,
    ) -> Table:
        """Create a table and write its first metadata file.

        Raises:
            NoSuchNamespaceError: If the namespace does not exist.
            TableAlreadyExistsError: If the table already exists.
        """
        format_version = int(
            properties.get(TableProperties.FORMAT_VERSION, TableProperties.DEFAULT_FORMAT_VERSION)
        )
        iceberg_schema = self._convert_schema_if_needed(schema, format_version)  # type: ignore[arg-type]
        namespace, table_name = self._split(identifier)
        if not self.namespace_exists(namespace):
            raise NoSuchNamespaceError(f"Namespace does not exist: {namespace}")
        if self._table_row(namespace, table_name) is not None:
            raise TableAlreadyExistsError(f"Table {namespace}.{table_name} already exists")
        location = self._resolve_table_location(location, namespace, table_name)
        provider = load_location_provider(table_location=location, table_properties=properties)
        metadata_location = provider.new_table_metadata_file_location()
        metadata = new_table_metadata(
            location=location,
            schema=iceberg_schema,
            partition_spec=partition_spec,
            sort_order=sort_order,
            properties=properties,
        )
        io = load_file_io(properties=self.properties, location=metadata_location)
        self._write_metadata(metadata, io, metadata_location)
        self._insert_table_row(namespace, table_name, metadata_location)
        return self.load_table(identifier)

    @override
    def register_table(
        self, identifier: str | Identifier, metadata_location: str, overwrite: bool = False
    ) -> Table:
        """Register an existing metadata file as a table.

        Raises:
            NotImplementedError: If ``overwrite`` is requested (SqlCatalog does not support it
                either).
            NoSuchNamespaceError: If the namespace does not exist.
            TableAlreadyExistsError: If the table already exists.
        """
        if overwrite:
            raise NotImplementedError("register_table(overwrite=True) is not supported")
        namespace, table_name = self._split(identifier)
        if not self.namespace_exists(namespace):
            raise NoSuchNamespaceError(f"Namespace does not exist: {namespace}")
        self._insert_table_row(namespace, table_name, metadata_location)
        return self.load_table(identifier)

    @override
    def load_table(self, identifier: str | Identifier) -> Table:
        """Load a table from its current metadata file.

        Raises:
            NoSuchTableError: If the table does not exist.
        """
        namespace, table_name = self._split(identifier)
        row = self._table_row(namespace, table_name)
        if row is None:
            raise NoSuchTableError(f"Table does not exist: {namespace}.{table_name}")
        metadata_location = row[0]
        if not metadata_location:
            raise NoSuchTableError(f"Table property {METADATA_LOCATION} is missing")
        io = load_file_io(properties=self.properties, location=metadata_location)
        metadata = FromInputFile.table_metadata(io.new_input(metadata_location))
        return Table(
            identifier=Catalog.identifier_to_tuple(namespace) + (table_name,),
            metadata=metadata,
            metadata_location=metadata_location,
            io=self._load_file_io(metadata.properties, metadata_location),
            catalog=self,
        )

    @override
    def drop_table(self, identifier: str | Identifier) -> None:
        """Remove a table from the catalog; its files are left in place.

        Raises:
            NoSuchTableError: If the table does not exist.
        """
        namespace, table_name = self._split(identifier)
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM iceberg_tables WHERE {_TABLE_ROW_FILTER}",
                (self.name, namespace, table_name),
            )
        if cursor.rowcount < 1:
            raise NoSuchTableError(f"Table does not exist: {namespace}.{table_name}")

    @override
    def rename_table(
        self, from_identifier: str | Identifier, to_identifier: str | Identifier
    ) -> Table:
        """Rename a table, possibly into another existing namespace.

        Raises:
            NoSuchTableError: If the source table does not exist.
            NoSuchNamespaceError: If the target namespace does not exist.
            TableAlreadyExistsError: If the target table already exists.
        """
        from_namespace, from_name = self._split(from_identifier)
        to_namespace, to_name = self._split(to_identifier)
        if not self.namespace_exists(to_namespace):
            raise NoSuchNamespaceError(f"Namespace does not exist: {to_namespace}")
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    f"UPDATE iceberg_tables SET table_namespace = ?, table_name = ?"
                    f" WHERE {_TABLE_ROW_FILTER}",
                    (to_namespace, to_name, self.name, from_namespace, from_name),
                )
        except sqlite3.IntegrityError as e:
            raise TableAlreadyExistsError(f"Table {to_namespace}.{to_name} already exists") from e
        if cursor.rowcount < 1:
            raise NoSuchTableError(f"Table does not exist: {from_namespace}.{from_name}")
        return self.load_table(to_identifier)

    @override
    def commit_table(
        self,
        table: Table,
        requirements: tuple[TableRequirement, ...],
        updates: tuple[TableUpdate, ...],
    ) -> CommitTableResponse:
        """Commit table updates with an optimistic check on ``metadata_location``.

        Raises:
            CommitFailedException: If a requirement does not hold against the current
                metadata, or another writer committed between this commit's read and write.
            TableAlreadyExistsError: If the commit creates a table that appeared meanwhile.
        """
        namespace, table_name = self._split(table.name())
        current: Table | None
        try:
            current = self.load_table(table.name())
        except NoSuchTableError:
            current = None
        staged = self._update_and_stage_table(current, table.name(), requirements, updates)
        if current is not None and staged.metadata == current.metadata:
            return _commit_response(current.metadata, current.metadata_location)
        self._write_metadata(staged.metadata, staged.io, staged.metadata_location)
        if current is None:
            self._insert_table_row(namespace, table_name, staged.metadata_location)
        else:
            with self._connect() as conn:
                cursor = conn.execute(
                    f"UPDATE iceberg_tables SET metadata_location = ?,"
                    f" previous_metadata_location = ?"
                    f" WHERE {_TABLE_ROW_FILTER} AND metadata_location = ?",
                    (
                        staged.metadata_location,
                        current.metadata_location,
                        self.name,
                        namespace,
                        table_name,
                        current.metadata_location,
                    ),
                )
            if cursor.rowcount < 1:
                raise CommitFailedException(
                    f"Table has been updated by another process: {namespace}.{table_name}"
                )
        return _commit_response(staged.metadata, staged.metadata_location)

    @override
    def namespace_exists(self, namespace: str | Identifier) -> bool:
        """Return whether the namespace, or a namespace nested under it, exists."""
        name = Catalog.namespace_to_string(
            Catalog.identifier_to_tuple(namespace), NoSuchNamespaceError
        )
        nested = name.replace("!", "!!").replace("_", "!_").replace("%", "!%") + ".%"
        with self._connect() as conn:
            for table, column in (
                ("iceberg_tables", "table_namespace"),
                ("iceberg_namespace_properties", "namespace"),
            ):
                row = conn.execute(
                    f"SELECT 1 FROM {table} WHERE catalog_name = ?"
                    f" AND ({column} = ? OR {column} LIKE ? ESCAPE '!') LIMIT 1",
                    (self.name, name, nested),
                ).fetchone()
                if row is not None:
                    return True
        return False

    @override
    def create_namespace(
        self, namespace: str | Identifier, properties: Properties = EMPTY_DICT
    ) -> None:
        """Create a namespace.

        Raises:
            NamespaceAlreadyExistsError: If it already exists.
        """
        if self.namespace_exists(namespace):
            raise NamespaceAlreadyExistsError(f"Namespace {namespace} already exists")
        name = Catalog.namespace_to_string(namespace, NoSuchNamespaceError)
        rows = properties or NAMESPACE_MINIMAL_PROPERTIES
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO iceberg_namespace_properties"
                " (catalog_name, namespace, property_key, property_value) VALUES (?, ?, ?, ?)",
                [(self.name, name, key, value) for key, value in rows.items()],
            )

    @override
    def drop_namespace(self, namespace: str | Identifier) -> None:
        """Drop an empty namespace.

        Raises:
            NoSuchNamespaceError: If it does not exist.
            NamespaceNotEmptyError: If it still holds tables.
        """
        if not self.namespace_exists(namespace):
            raise NoSuchNamespaceError(f"Namespace does not exist: {namespace}")
        name = Catalog.namespace_to_string(namespace)
        if tables := self.list_tables(namespace):
            raise NamespaceNotEmptyError(f"Namespace {name} is not empty: {len(tables)} tables")
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM iceberg_namespace_properties WHERE catalog_name = ? AND namespace = ?",
                (self.name, name),
            )

    @override
    def list_tables(self, namespace: str | Identifier) -> list[Identifier]:
        """List the tables directly in a namespace.

        Raises:
            NoSuchNamespaceError: If the namespace does not exist.
        """
        if namespace and not self.namespace_exists(namespace):
            raise NoSuchNamespaceError(f"Namespace does not exist: {namespace}")
        name = Catalog.namespace_to_string(namespace)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT table_namespace, table_name FROM iceberg_tables"
                " WHERE catalog_name = ? AND table_namespace = ?"
                " AND (iceberg_type = 'TABLE' OR iceberg_type IS NULL)"
                " ORDER BY table_name",
                (self.name, name),
            ).fetchall()
        return [Catalog.identifier_to_tuple(ns) + (table_name,) for ns, table_name in rows]

    @override
    def list_namespaces(self, namespace: str | Identifier = ()) -> list[Identifier]:
        """List the namespaces one level below ``namespace`` (top level by default).

        Raises:
            NoSuchNamespaceError: If ``namespace`` is given and does not exist.
        """
        if namespace and not self.namespace_exists(namespace):
            raise NoSuchNamespaceError(f"Namespace does not exist: {namespace}")
        parent = Catalog.identifier_to_tuple(namespace)
        with self._connect() as conn:
            names = [
                row[0]
                for row in conn.execute(
                    "SELECT table_namespace FROM iceberg_tables WHERE catalog_name = ?"
                    " UNION SELECT namespace FROM iceberg_namespace_properties"
                    " WHERE catalog_name = ?",
                    (self.name, self.name),
                )
            ]
        depth = len(parent) + 1
        children = {
            ns[:depth]
            for ns in (Catalog.identifier_to_tuple(name) for name in names)
            if len(ns) >= depth and ns[: depth - 1] == parent
        }
        return sorted(children)

    @override
    def load_namespace_properties(self, namespace: str | Identifier) -> Properties:
        """Return a namespace's properties.

        Raises:
            NoSuchNamespaceError: If it does not exist.
        """
        name = Catalog.namespace_to_string(namespace)
        if not self.namespace_exists(namespace):
            raise NoSuchNamespaceError(f"Namespace {name} does not exist")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT property_key, property_value FROM iceberg_namespace_properties"
                " WHERE catalog_name = ? AND namespace = ?",
                (self.name, name),
            ).fetchall()
        return {key: value for key, value in rows}

    @override
    def update_namespace_properties(
        self,
        namespace: str | Identifier,
        removals: set[str] | None = None,
        updates: Properties = EMPTY_DICT,
    ) -> PropertiesUpdateSummary:
        """Remove and set namespace properties in one transaction.

        Raises:
            NoSuchNamespaceError: If it does not exist.
            ValueError: If ``removals`` and ``updates`` overlap.
        """
        name = Catalog.namespace_to_string(namespace)
        current = self.load_namespace_properties(namespace)
        summary, _ = self._get_updated_props_and_update_summary(
            current_properties=current, removals=removals, updates=updates
        )
        delete_keys = list((removals or set()) | set(updates))
        with self._connect() as conn:
            conn.executemany(
                "DELETE FROM iceberg_namespace_properties"
                " WHERE catalog_name = ? AND namespace = ? AND property_key = ?",
                [(self.name, name, key) for key in delete_keys],
            )
            conn.executemany(
                "INSERT INTO iceberg_namespace_properties"
                " (catalog_name, namespace, property_key, property_value) VALUES (?, ?, ?, ?)",
                [(self.name, name, key, value) for key, value in updates.items()],
            )
        return summary

    @override
    def list_views(self, namespace: str | Identifier) -> list[Identifier]:
        """Return no views: views are not supported by this catalog."""
        return []

    @override
    def view_exists(self, identifier: str | Identifier) -> bool:
        """Return False: views are not supported by this catalog."""
        return False

    @override
    def load_view(self, identifier: str | Identifier) -> View:
        """Views are not supported by this catalog.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("LocalCatalog does not support views")

    @override
    def create_view(
        self,
        identifier: str | Identifier,
        schema: "Schema | pa.Schema",
        view_version: ViewVersion,
        location: str | None = None,
        properties: Properties = EMPTY_DICT,
    ) -> View:
        """Views are not supported by this catalog.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("LocalCatalog does not support views")

    @override
    def register_view(self, identifier: str | Identifier, metadata_location: str) -> View:
        """Views are not supported by this catalog.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("LocalCatalog does not support views")

    @override
    def drop_view(self, identifier: str | Identifier) -> None:
        """Views are not supported by this catalog.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("LocalCatalog does not support views")
