"""Idempotent writes of bronze frames to the Iceberg table ``option_chain``.

The unit of a write is one slice: one ``trade_date`` from one ``source``. ``write_partition``
replaces the slice in a single Iceberg overwrite (delete the slice's rows, append the new
ones, one commit), so loading a day again changes nothing when the data is unchanged, and a
corrected load fully replaces the earlier one. Other sources on the same date are untouched.
Every write is a new Iceberg snapshot; the replaced data stays readable by time travel until
snapshots are expired.

The table is partitioned by ``day(trade_date)`` and ``identity(source)``, so replacing a
slice drops whole data files instead of rewriting them, and each slice maps to its own
files (see ``partition_file_counts``).

The catalog comes from the environment (``catalog_from_env``):

* ``OAP_ICEBERG_CATALOG=sql`` (the default, alias ``local``) is ``LocalCatalog``, a SQLite
  catalog with a file warehouse, for development, tests and the local Airflow stack
  (ADR 0005 explains why it is not pyiceberg's SqlCatalog).
* ``OAP_ICEBERG_CATALOG=glue`` is the AWS Glue Data Catalog with an S3 warehouse, the
  production bronze layer (ADR 0001).

The catalog and the files are the I/O boundary; ``content_hash`` is pure.
"""

import hashlib
import json
import logging
import os
import warnings
from collections import Counter
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.catalog.glue import GlueCatalog
from pyiceberg.exceptions import CommitFailedException, NoSuchTableError, TableAlreadyExistsError
from pyiceberg.expressions import BooleanExpression
from pyiceberg.expressions.parser import parse as parse_filter
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import DayTransform, IdentityTransform
from pyiceberg.types import (
    DateType,
    DecimalType,
    DoubleType,
    IcebergType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_random_exponential

from oap.ingest.local_catalog import LocalCatalog, sqlite_path
from oap.ingest.schema import BRONZE_FRAME, BRONZE_SCHEMA, KEY_COLUMNS, SOURCES, to_arrow

logger = logging.getLogger(__name__)

TABLE_NAME = "option_chain"
"""Table name inside the namespace."""

DEFAULT_NAMESPACE = "bronze"
"""Namespace used unless the Glue catalog names its database in ``OAP_GLUE_DATABASE``."""

TABLE_IDENTIFIER: tuple[str, str] = (DEFAULT_NAMESPACE, TABLE_NAME)
"""Default ``(namespace, table)`` identifier of the bronze option chain table."""

DEFAULT_LOCAL_DIR = ".iceberg-local"
"""Directory, relative to the working directory, of the default local catalog and warehouse."""

CATALOG_NAME = "oap"
"""Name of the catalog; the local catalog stores it in every row's ``catalog_name``."""

LOCAL_CATALOG_KINDS = frozenset({"sql", "local"})
"""``OAP_ICEBERG_CATALOG`` values that select the local SQLite catalog."""

COMMIT_ATTEMPTS = 5
"""Attempts per slice overwrite when a concurrent writer commits first."""

_FILE_SCHEME = "file://"
_DATA_FILE_CONTENT = 0

_ICEBERG_TYPES: dict[pa.DataType, IcebergType] = {
    pa.date32(): DateType(),
    pa.string(): StringType(),
    pa.decimal128(10, 3): DecimalType(10, 3),
    pa.float64(): DoubleType(),
    pa.int64(): LongType(),
    pa.timestamp("us", tz="UTC"): TimestamptzType(),
}
_FIELD_IDS: dict[str, int] = {name: i for i, name in enumerate(BRONZE_SCHEMA.names, start=1)}


def _catalog_kind(env: Mapping[str, str]) -> str:
    """Return ``glue`` or ``sql`` from ``OAP_ICEBERG_CATALOG`` (``local`` is an alias of sql)."""
    kind = env.get("OAP_ICEBERG_CATALOG", "").strip().lower() or "sql"
    if kind in LOCAL_CATALOG_KINDS:
        return "sql"
    if kind == "glue":
        return "glue"
    raise ValueError(f"OAP_ICEBERG_CATALOG must be sql, local or glue, got {kind!r}")


def _source_literal(source: str) -> str:
    """Return ``source`` as a quoted filter literal; only known feeds are accepted."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(SOURCES)}")
    return f"'{source}'"


def _slice_filter(trade_date: date, source: str) -> BooleanExpression:
    """Rows of one (trade_date, source) slice; values are validated before interpolation."""
    return parse_filter(
        f"trade_date = '{trade_date.isoformat()}' AND source = {_source_literal(source)}"
    )


def _scan(table: Table, row_filter: BooleanExpression) -> pd.DataFrame:
    """Read matching rows from the current snapshot as a bronze-typed frame."""
    arrow = table.scan(row_filter=row_filter).to_arrow()
    typed = arrow.select(BRONZE_SCHEMA.names).cast(BRONZE_SCHEMA)
    return typed.to_pandas(types_mapper=pd.ArrowDtype)


def bronze_iceberg_schema() -> Schema:
    """Return BRONZE_SCHEMA as an Iceberg schema, field ids 1 to 20 in column order.

    Returns:
        The Iceberg schema: dates as ``date``, the strike as ``decimal(10, 3)``, prices and
        greeks as ``double``, counts as ``long`` and ``ingested_at`` as ``timestamptz``.
    """
    return Schema(
        *(
            NestedField(
                field_id=_FIELD_IDS[field.name],
                name=field.name,
                field_type=_ICEBERG_TYPES[field.type],
                required=not field.nullable,
            )
            for field in BRONZE_SCHEMA
        )
    )


def table_identifier(env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Return the ``(namespace, table)`` identifier the environment selects.

    The namespace is ``OAP_GLUE_DATABASE`` when ``OAP_ICEBERG_CATALOG`` is ``glue`` and that
    variable is set (for example ``oap_bronze``); otherwise ``bronze``.

    Args:
        env: Environment to read; ``os.environ`` when omitted.

    Returns:
        The identifier, for example ``("bronze", "option_chain")``.
    """
    env = os.environ if env is None else env
    database = env.get("OAP_GLUE_DATABASE", "").strip()
    if _catalog_kind(env) == "glue" and database:
        return (database, TABLE_NAME)
    return TABLE_IDENTIFIER


def catalog_from_env(env: Mapping[str, str] | None = None) -> Catalog:
    """Load the Iceberg catalog the environment selects.

    ``OAP_ICEBERG_CATALOG`` picks the implementation:

    * ``sql`` (default; ``local`` is an alias): ``LocalCatalog``, URI from ``OAP_ICEBERG_URI``
      (default ``sqlite:///.iceberg-local/catalog.db``), warehouse from
      ``OAP_ICEBERG_WAREHOUSE`` (default ``file://<absolute cwd>/.iceberg-local/warehouse``).
      Relative paths in either, such as ``sqlite:///.iceberg-local/catalog.db`` or
      ``file://./.iceberg-local/warehouse``, resolve against the working directory at call
      time. Nothing is created here: the catalog's directory and database appear on its first
      operation (``ensure_table``), and pyiceberg creates warehouse directories as it writes.
    * ``glue``: warehouse from ``OAP_ICEBERG_WAREHOUSE``, an ``s3://bucket/prefix`` URI;
      region from ``AWS_REGION`` when set. Credentials come from the usual AWS chain.

    Args:
        env: Environment to read; ``os.environ`` when omitted.

    Returns:
        The catalog. No table is created.

    Raises:
        ValueError: If ``OAP_ICEBERG_CATALOG`` is not ``sql``, ``local`` or ``glue``, ``glue``
            is selected without an ``s3://`` warehouse, or the URI is not ``sqlite:///``.
    """
    env = os.environ if env is None else env
    kind = _catalog_kind(env)
    if kind == "glue":
        warehouse = env.get("OAP_ICEBERG_WAREHOUSE", "").strip()
        if not warehouse.startswith("s3://"):
            raise ValueError(
                f"OAP_ICEBERG_CATALOG=glue needs OAP_ICEBERG_WAREHOUSE=s3://..., got {warehouse!r}"
            )
        properties = {"warehouse": warehouse}
        region = env.get("AWS_REGION", "").strip()
        if region:
            properties["glue.region"] = region
            properties["client.region"] = region
        return GlueCatalog(CATALOG_NAME, **properties)
    uri = env.get("OAP_ICEBERG_URI", "").strip() or f"sqlite:///{DEFAULT_LOCAL_DIR}/catalog.db"
    db_path = sqlite_path(uri).absolute()
    warehouse = env.get("OAP_ICEBERG_WAREHOUSE", "").strip() or (
        (Path.cwd() / DEFAULT_LOCAL_DIR / "warehouse").as_uri()
    )
    if warehouse.startswith(_FILE_SCHEME):
        warehouse = Path(warehouse.removeprefix(_FILE_SCHEME)).absolute().as_uri()
    return LocalCatalog(CATALOG_NAME, uri=f"sqlite:///{db_path}", warehouse=warehouse)


def bronze_partition_spec() -> PartitionSpec:
    """Return the bronze partition spec: ``day(trade_date)`` then ``identity(source)``.

    Field ids are bound to BRONZE_SCHEMA's field ids as assigned by ``ensure_table``.

    Returns:
        The partition spec, fields named ``trade_date_day`` and ``source``.
    """
    return PartitionSpec(
        PartitionField(
            source_id=_FIELD_IDS["trade_date"],
            field_id=1000,
            transform=DayTransform(),
            name="trade_date_day",
        ),
        PartitionField(
            source_id=_FIELD_IDS["source"],
            field_id=1001,
            transform=IdentityTransform(),
            name="source",
        ),
    )


def ensure_table(catalog: Catalog, identifier: tuple[str, str] = TABLE_IDENTIFIER) -> Table:
    """Return the bronze table, creating its namespace and the table if missing.

    A new table gets BRONZE_SCHEMA and ``bronze_partition_spec()``. An existing table is
    never altered, but it must hold every BRONZE_SCHEMA column with the same type and
    nullability; a table created by an older contract (for example with a two-decimal
    strike) is reported instead of being written to with a mismatched schema.

    Args:
        catalog: Catalog to create the table in.
        identifier: ``(namespace, table)``.

    Returns:
        The loaded table.

    Raises:
        ValueError: If an existing table's schema differs from BRONZE_SCHEMA; the message
            lists the differing columns.
    """
    namespace = identifier[0]
    catalog.create_namespace_if_not_exists(namespace)
    try:
        table = catalog.load_table(identifier)
    except NoSuchTableError:
        try:
            return catalog.create_table(
                identifier, schema=bronze_iceberg_schema(), partition_spec=bronze_partition_spec()
            )
        except TableAlreadyExistsError:
            table = catalog.load_table(identifier)
    _check_schema(table)
    return table


def _check_schema(table: Table) -> None:
    """Raise ValueError if ``table`` lacks a bronze column or holds it with another type."""
    actual = {f.name: (f.field_type, f.required) for f in table.schema().fields}
    differences = [
        f"{f.name}: expected {f.field_type}{' required' if f.required else ''}, "
        f"found {actual[f.name][0] if f.name in actual else 'nothing'}"
        for f in bronze_iceberg_schema().fields
        if actual.get(f.name) != (f.field_type, f.required)
    ]
    if differences:
        raise ValueError(
            f"table {'.'.join(table.name())} does not match the bronze schema: "
            + "; ".join(differences)
        )


def write_partition(table: Table, frame: pd.DataFrame, *, trade_date: date, source: str) -> int:
    """Replace one (trade_date, source) slice of the table with ``frame``, atomically.

    Validates ``frame`` with ``BRONZE_FRAME.validate(frame, lazy=True)``, then commits one
    overwrite whose filter is ``trade_date == trade_date AND source == source``. An empty
    frame deletes the slice. If another writer commits first (``CommitFailedException``), the
    table is refreshed and the overwrite retried, up to ``COMMIT_ATTEMPTS`` times; replacing a
    slice is idempotent, so a retry is safe. Logs one INFO line per write.

    Args:
        table: The bronze table.
        frame: Rows for exactly this slice.
        trade_date: Session date of the slice.
        source: Feed of the slice, one of ``SOURCES``.

    Returns:
        Number of rows written; 0 for an empty frame.

    Raises:
        ValueError: If ``source`` is not in ``SOURCES``, or any row has a different
            ``trade_date`` or ``source`` than the slice.
        pandera.errors.SchemaErrors: If ``frame`` breaks the bronze contract; every failed
            check is listed. Nothing is committed.
        pyiceberg.exceptions.CommitFailedException: If every attempt lost a commit race.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(SOURCES)}")
    validated = BRONZE_FRAME.validate(frame, lazy=True)
    other_dates = set(validated["trade_date"]) - {trade_date}
    if other_dates:
        raise ValueError(f"frame holds trade dates {sorted(other_dates)}, slice is {trade_date}")
    other_sources = set(validated["source"]) - {source}
    if other_sources:
        raise ValueError(f"frame holds sources {sorted(other_sources)}, slice is {source!r}")
    arrow = to_arrow(validated)
    slice_filter = _slice_filter(trade_date, source)
    for attempt in Retrying(
        stop=stop_after_attempt(COMMIT_ATTEMPTS),
        wait=wait_random_exponential(multiplier=0.2, max=5),
        retry=retry_if_exception_type(CommitFailedException),
        reraise=True,
    ):
        with attempt:
            table.refresh()
            with warnings.catch_warnings():
                # pyiceberg warns when the delete half of an overwrite matches nothing, which
                # is the normal case for a first load.
                warnings.filterwarnings("ignore", message="Delete operation did not match")
                table.overwrite(arrow, overwrite_filter=slice_filter)
    logger.info(
        "bronze %s %s: wrote %d rows to %s", source, trade_date, len(arrow), ".".join(table.name())
    )
    return len(arrow)


def read_partition(table: Table, *, trade_date: date, source: str) -> pd.DataFrame:
    """Read one (trade_date, source) slice from the current snapshot.

    Args:
        table: The bronze table.
        trade_date: Session date of the slice.
        source: Feed of the slice.

    Returns:
        A frame with BRONZE_SCHEMA's columns and dtypes; empty if the slice holds no rows.

    Raises:
        ValueError: If ``source`` is not in ``SOURCES``.
    """
    return _scan(table, _slice_filter(trade_date, source))


def read_range(table: Table, *, start: date, end: date, source: str | None = None) -> pd.DataFrame:
    """Read every row with ``start <= trade_date <= end`` from the current snapshot.

    Args:
        table: The bronze table.
        start: First trade date, inclusive.
        end: Last trade date, inclusive.
        source: Restrict to one feed; every feed when None.

    Returns:
        A frame with BRONZE_SCHEMA's columns and dtypes.

    Raises:
        ValueError: If ``start`` is after ``end`` or ``source`` is not in ``SOURCES``.
    """
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    text = f"trade_date >= '{start.isoformat()}' AND trade_date <= '{end.isoformat()}'"
    if source is not None:
        text += f" AND source = {_source_literal(source)}"
    return _scan(table, parse_filter(text))


def partition_file_counts(table: Table) -> dict[tuple[date, str], int]:
    """Count live data files per (trade_date, source) slice in the current snapshot.

    Reads the ``partition`` column of ``table.inspect.files()``; this works because
    ``source`` is a partition field, so every data file belongs to exactly one slice.

    Args:
        table: The bronze table.

    Returns:
        ``(trade_date, source)`` to number of data files. Slices with no files are absent.
    """
    if table.current_snapshot() is None:
        return {}
    files = table.inspect.files()
    counts: Counter[tuple[date, str]] = Counter()
    for content, partition in zip(
        files.column("content").to_pylist(), files.column("partition").to_pylist(), strict=True
    ):
        if content == _DATA_FILE_CONTENT:
            values = cast(dict[str, Any], partition)
            counts[(values["trade_date_day"], values["source"])] += 1
    return dict(counts)


def content_hash(frame: pd.DataFrame) -> str:
    """Hash the content of a bronze frame, independent of row order and load time.

    Drops ``ingested_at``, sorts by ``(occ_symbol, trade_date, source)`` and hashes a
    deterministic serialisation of the remaining columns, so two loads of the same data hash
    equal and any changed value, added or removed row changes the hash.

    Args:
        frame: A frame with BRONZE_SCHEMA's columns.

    Returns:
        Lower-case hexadecimal SHA-256 digest, 64 characters.
    """
    columns = [name for name in BRONZE_SCHEMA.names if name != "ingested_at"]
    ordered = frame[columns].sort_values(
        [*KEY_COLUMNS, *(c for c in columns if c not in KEY_COLUMNS)], kind="mergesort"
    )
    schema = pa.schema([BRONZE_SCHEMA.field(name) for name in columns])
    rows = pa.Table.from_pandas(ordered, schema=schema, preserve_index=False).to_pylist()
    payload = json.dumps(rows, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
