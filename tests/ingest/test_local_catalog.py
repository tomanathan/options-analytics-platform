import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from pyiceberg.exceptions import (
    CommitFailedException,
    NamespaceAlreadyExistsError,
    NamespaceNotEmptyError,
    NoSuchNamespaceError,
    NoSuchTableError,
    TableAlreadyExistsError,
)
from pyiceberg.io import FileIO
from pyiceberg.schema import Schema
from pyiceberg.table.metadata import TableMetadata
from pyiceberg.types import LongType, NestedField, StringType

from oap.ingest.local_catalog import CREATE_TABLES_SQL, LocalCatalog, sqlite_path

SCHEMA = Schema(
    NestedField(field_id=1, name="id", field_type=LongType(), required=True),
    NestedField(field_id=2, name="name", field_type=StringType(), required=False),
)
ARROW_FIELDS: "list[pa.Field[Any]]" = [
    pa.field("id", pa.int64(), nullable=False),
    pa.field("name", pa.string()),
]
ARROW_SCHEMA = pa.schema(ARROW_FIELDS)

# Column layout of pyiceberg 0.12 SqlCatalog's v1 schema (pyiceberg/catalog/sql.py).
SQLCATALOG_TABLES_COLUMNS = [
    "catalog_name",
    "table_namespace",
    "table_name",
    "metadata_location",
    "previous_metadata_location",
    "iceberg_type",
]
SQLCATALOG_NAMESPACE_COLUMNS = ["catalog_name", "namespace", "property_key", "property_value"]


def _rows(n: int, start: int = 0) -> pa.Table:
    return pa.table(
        {"id": list(range(start, start + n)), "name": [f"r{i}" for i in range(n)]},
        schema=ARROW_SCHEMA,
    )


def _open(tmp_path: Path) -> LocalCatalog:
    return LocalCatalog(
        "oap", uri=f"sqlite:///{tmp_path}/catalog.db", warehouse=(tmp_path / "wh").as_uri()
    )


@pytest.fixture
def catalog(tmp_path: Path) -> LocalCatalog:
    return _open(tmp_path)


def _columns(db: Path, table: str) -> list[tuple[str, int]]:
    with sqlite3.connect(db) as conn:
        return [(row[1], row[5]) for row in conn.execute(f"PRAGMA table_info({table})")]


# construction


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("sqlite:///.iceberg-local/catalog.db", Path(".iceberg-local/catalog.db")),
        ("sqlite:////tmp/x/catalog.db", Path("/tmp/x/catalog.db")),
    ],
)
def test_sqlite_path_parses_relative_and_absolute_uris(uri: str, expected: Path) -> None:
    assert sqlite_path(uri) == expected


@pytest.mark.parametrize(
    "uri", ["postgresql://localhost/db", "sqlite:///:memory:", "sqlite:///", "catalog.db"]
)
def test_sqlite_path_rejects_other_uris(uri: str) -> None:
    with pytest.raises(ValueError):
        sqlite_path(uri)


def test_catalog_requires_a_uri() -> None:
    with pytest.raises(ValueError):
        LocalCatalog("oap", warehouse="file:///tmp/wh")


# layout compatibility with pyiceberg's SqlCatalog


def test_ddl_names_exactly_the_sqlcatalog_columns() -> None:
    tables_ddl, namespace_ddl = CREATE_TABLES_SQL

    assert "CREATE TABLE IF NOT EXISTS iceberg_tables" in tables_ddl
    for column in SQLCATALOG_TABLES_COLUMNS:
        assert f" {column} " in tables_ddl
    assert "PRIMARY KEY (catalog_name, table_namespace, table_name)" in tables_ddl
    assert "CREATE TABLE IF NOT EXISTS iceberg_namespace_properties" in namespace_ddl
    for column in SQLCATALOG_NAMESPACE_COLUMNS:
        assert f" {column} " in namespace_ddl
    assert "PRIMARY KEY (catalog_name, namespace, property_key)" in namespace_ddl


def test_database_file_has_the_sqlcatalog_layout(tmp_path: Path, catalog: LocalCatalog) -> None:
    db = tmp_path / "catalog.db"

    tables = _columns(db, "iceberg_tables")
    namespaces = _columns(db, "iceberg_namespace_properties")

    assert [name for name, _ in tables] == SQLCATALOG_TABLES_COLUMNS
    assert [name for name, pk in tables if pk] == ["catalog_name", "table_namespace", "table_name"]
    assert [name for name, _ in namespaces] == SQLCATALOG_NAMESPACE_COLUMNS
    assert [name for name, pk in namespaces if pk] == [
        "catalog_name",
        "namespace",
        "property_key",
    ]


def test_table_rows_are_typed_as_tables(tmp_path: Path, catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_table(("bronze", "t"), SCHEMA)

    with sqlite3.connect(tmp_path / "catalog.db") as conn:
        rows = conn.execute(
            "SELECT catalog_name, table_namespace, table_name, iceberg_type FROM iceberg_tables"
        ).fetchall()
    assert rows == [("oap", "bronze", "t", "TABLE")]


def test_reopening_the_file_creates_nothing_twice(tmp_path: Path) -> None:
    first = _open(tmp_path)
    first.create_namespace("bronze")

    second = _open(tmp_path)

    assert second.list_namespaces() == [("bronze",)]


# namespaces


def test_new_namespace_gets_the_minimal_properties(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")

    assert catalog.load_namespace_properties("bronze") == {"exists": "true"}


def test_create_namespace_if_not_exists_is_idempotent(catalog: LocalCatalog) -> None:
    catalog.create_namespace_if_not_exists("bronze")
    catalog.create_namespace_if_not_exists("bronze")

    assert catalog.list_namespaces() == [("bronze",)]


def test_create_namespace_twice_raises(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")

    with pytest.raises(NamespaceAlreadyExistsError):
        catalog.create_namespace("bronze")


def test_namespace_properties_round_trip(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze", {"owner": "oap", "tier": "raw"})

    summary = catalog.update_namespace_properties(
        "bronze", removals={"tier", "missing"}, updates={"owner": "ingest", "new": "x"}
    )

    assert catalog.load_namespace_properties("bronze") == {"owner": "ingest", "new": "x"}
    assert sorted(summary.removed) == ["tier"]
    assert sorted(summary.updated) == ["new", "owner"]
    assert summary.missing == ["missing"]


def test_list_namespaces_by_level(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_namespace(("silver", "staging"))

    assert catalog.list_namespaces() == [("bronze",), ("silver",)]
    assert catalog.list_namespaces("silver") == [("silver", "staging")]


def test_drop_namespace(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")

    catalog.drop_namespace("bronze")

    assert catalog.list_namespaces() == []
    assert not catalog.namespace_exists("bronze")


def test_drop_missing_namespace_raises(catalog: LocalCatalog) -> None:
    with pytest.raises(NoSuchNamespaceError):
        catalog.drop_namespace("nope")


def test_drop_non_empty_namespace_raises(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_table(("bronze", "t"), SCHEMA)

    with pytest.raises(NamespaceNotEmptyError):
        catalog.drop_namespace("bronze")


def test_load_properties_of_a_missing_namespace_raises(catalog: LocalCatalog) -> None:
    with pytest.raises(NoSuchNamespaceError):
        catalog.load_namespace_properties("nope")


# tables


def test_create_and_load_table_round_trip(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")

    created = catalog.create_table(("bronze", "t"), SCHEMA)
    loaded = catalog.load_table(("bronze", "t"))

    assert loaded.name() == ("bronze", "t")
    assert loaded.metadata_location == created.metadata_location
    assert loaded.schema() == SCHEMA
    assert loaded.location().endswith("/wh/bronze/t")
    assert catalog.list_tables("bronze") == [("bronze", "t")]
    assert catalog.table_exists(("bronze", "t"))


def test_create_existing_table_raises(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_table(("bronze", "t"), SCHEMA)

    with pytest.raises(TableAlreadyExistsError):
        catalog.create_table(("bronze", "t"), SCHEMA)


def test_create_table_in_a_missing_namespace_raises(catalog: LocalCatalog) -> None:
    with pytest.raises(NoSuchNamespaceError):
        catalog.create_table(("nope", "t"), SCHEMA)


def test_load_missing_table_raises(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")

    with pytest.raises(NoSuchTableError):
        catalog.load_table(("bronze", "missing"))
    assert not catalog.table_exists(("bronze", "missing"))


def test_appends_survive_reopening_the_catalog(tmp_path: Path, catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    table = catalog.create_table(("bronze", "t"), SCHEMA)
    table.append(_rows(3))
    table.append(_rows(2, start=3))

    reopened = _open(tmp_path).load_table(("bronze", "t"))

    assert reopened.metadata_location == table.metadata_location
    ids = reopened.scan().to_arrow().column("id").to_pylist()
    assert sorted(i for i in ids if i is not None) == [0, 1, 2, 3, 4]
    assert len(reopened.snapshots()) == 2


def test_commit_records_the_previous_metadata_location(
    tmp_path: Path, catalog: LocalCatalog
) -> None:
    catalog.create_namespace("bronze")
    table = catalog.create_table(("bronze", "t"), SCHEMA)
    before = table.metadata_location

    table.append(_rows(1))

    with sqlite3.connect(tmp_path / "catalog.db") as conn:
        row = conn.execute(
            "SELECT metadata_location, previous_metadata_location FROM iceberg_tables"
        ).fetchone()
    assert row == (table.metadata_location, before)


def test_drop_table(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_table(("bronze", "t"), SCHEMA)

    catalog.drop_table(("bronze", "t"))

    assert catalog.list_tables("bronze") == []
    with pytest.raises(NoSuchTableError):
        catalog.drop_table(("bronze", "t"))


def test_rename_table_across_namespaces(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_namespace("archive")
    table = catalog.create_table(("bronze", "t"), SCHEMA)
    table.append(_rows(2))

    renamed = catalog.rename_table(("bronze", "t"), ("archive", "t_old"))

    assert renamed.name() == ("archive", "t_old")
    assert len(renamed.scan().to_arrow()) == 2
    assert catalog.list_tables("bronze") == []


def test_rename_onto_an_existing_table_raises(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_table(("bronze", "a"), SCHEMA)
    catalog.create_table(("bronze", "b"), SCHEMA)

    with pytest.raises(TableAlreadyExistsError):
        catalog.rename_table(("bronze", "a"), ("bronze", "b"))


def test_rename_missing_table_raises(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")

    with pytest.raises(NoSuchTableError):
        catalog.rename_table(("bronze", "a"), ("bronze", "b"))


def test_rename_into_a_missing_namespace_raises(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_table(("bronze", "a"), SCHEMA)

    with pytest.raises(NoSuchNamespaceError):
        catalog.rename_table(("bronze", "a"), ("nope", "a"))


def test_register_table_from_existing_metadata(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    table = catalog.create_table(("bronze", "t"), SCHEMA)
    table.append(_rows(4))

    registered = catalog.register_table(("bronze", "copy"), table.metadata_location)

    assert len(registered.scan().to_arrow()) == 4


# optimistic concurrency

# pyiceberg 0.12 retries snapshot commits itself (commit.retry.num-retries, default 4), so the
# catalog-level conflict is observed with its retries switched off.
NO_RETRIES = {"commit.retry.num-retries": "0"}


def test_commit_from_a_stale_table_raises(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")
    catalog.create_table(("bronze", "t"), SCHEMA, properties=NO_RETRIES)
    first = catalog.load_table(("bronze", "t"))
    stale = catalog.load_table(("bronze", "t"))
    first.append(_rows(1))

    with pytest.raises(CommitFailedException):
        stale.append(_rows(1, start=10))
    assert catalog.load_table(("bronze", "t")).scan().to_arrow().column("id").to_pylist() == [0]


def test_pyiceberg_retries_a_stale_append_against_the_refreshed_table(
    catalog: LocalCatalog,
) -> None:
    catalog.create_namespace("bronze")
    catalog.create_table(("bronze", "t"), SCHEMA)
    first = catalog.load_table(("bronze", "t"))
    stale = catalog.load_table(("bronze", "t"))
    first.append(_rows(1))

    stale.append(_rows(1, start=10))

    ids = catalog.load_table(("bronze", "t")).scan().to_arrow().column("id").to_pylist()
    assert sorted(i for i in ids if i is not None) == [0, 10]


def test_a_commit_racing_between_read_and_write_raises(
    tmp_path: Path, catalog: LocalCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog.create_namespace("bronze")
    table = catalog.create_table(("bronze", "t"), SCHEMA, properties=NO_RETRIES)
    write_metadata: Callable[[TableMetadata, FileIO, str], None] = catalog._write_metadata

    def write_then_race(metadata: TableMetadata, io: FileIO, path: str) -> None:
        write_metadata(metadata, io, path)
        with sqlite3.connect(tmp_path / "catalog.db") as conn:
            conn.execute("UPDATE iceberg_tables SET metadata_location = 'file:///elsewhere'")

    monkeypatch.setattr(catalog, "_write_metadata", write_then_race)

    with pytest.raises(CommitFailedException):
        table.append(_rows(1))
    with sqlite3.connect(tmp_path / "catalog.db") as conn:
        location = conn.execute("SELECT metadata_location FROM iceberg_tables").fetchone()
    assert location == ("file:///elsewhere",)


# views


def test_views_are_not_supported(catalog: LocalCatalog) -> None:
    catalog.create_namespace("bronze")

    assert catalog.list_views("bronze") == []
    assert not catalog.view_exists(("bronze", "v"))
    with pytest.raises(NotImplementedError):
        catalog.load_view(("bronze", "v"))
    with pytest.raises(NotImplementedError):
        catalog.drop_view(("bronze", "v"))
