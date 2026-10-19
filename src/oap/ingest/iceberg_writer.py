"""Idempotent writes of bronze frames to the Iceberg tables of the bronze layer.

The unit of a write is one slice: one ``trade_date`` from one ``source``. ``write_partition``
replaces the slice in a single Iceberg overwrite (delete the slice's rows, append the new
ones, one commit), so loading a day again changes nothing when the data is unchanged, and a
corrected load fully replaces the earlier one. Other sources on the same date are untouched.
Every write is a new Iceberg snapshot; the replaced data stays readable by time travel until
snapshots are expired.

Every bronze table (``oap.ingest.tables.BRONZE_TABLES``: ``option_chain`` and
``underlying_price``) is partitioned by ``day(trade_date)`` and ``identity(source)``, so
replacing a slice drops whole data files instead of rewriting them, and each slice maps to
its own files (see ``partition_file_counts``). The functions here are generic over a
``TableSpec``: callers may pass ``spec=``, and otherwise it is detected from the table's name,
so a frame can never be validated against another table's contract. ``ensure_table``,
``table_identifier`` and ``content_hash`` default to the option chain, which keeps the calls
written before the second table existed working unchanged.

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
from pyiceberg.partitioning import PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_random_exponential

from oap.ingest.local_catalog import LocalCatalog, sqlite_path
from oap.ingest.schema import to_arrow
from oap.ingest.tables import OPTION_CHAIN, TableSpec, spec_for

logger = logging.getLogger(__name__)

TABLE_NAME = OPTION_CHAIN.name
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


def _catalog_kind(env: Mapping[str, str]) -> str:
    """Return ``glue`` or ``sql`` from ``OAP_ICEBERG_CATALOG`` (``local`` is an alias of sql)."""
    kind = env.get("OAP_ICEBERG_CATALOG", "").strip().lower() or "sql"
    if kind in LOCAL_CATALOG_KINDS:
        return "sql"
    if kind == "glue":
        return "glue"
    raise ValueError(f"OAP_ICEBERG_CATALOG must be sql, local or glue, got {kind!r}")


def _source_literal(source: str, spec: TableSpec) -> str:
    """Return ``source`` as a quoted filter literal; only the table's feeds are accepted."""
    if source not in spec.sources:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(spec.sources)}")
    return f"'{source}'"


def _slice_filter(trade_date: date, source: str, spec: TableSpec) -> BooleanExpression:
    """Rows of one (trade_date, source) slice; values are validated before interpolation."""
    return parse_filter(
        f"trade_date = '{trade_date.isoformat()}' AND source = {_source_literal(source, spec)}"
    )


def _resolve(table: Table, spec: TableSpec | None) -> TableSpec:
    """Return the spec of ``table``, detected from its name.

    Args:
        table: A bronze table.
        spec: The spec the caller expects, or None to accept the detected one.

    Returns:
        The spec whose name is the last part of the table's identifier.

    Raises:
        ValueError: If the table's name is not a bronze table, or ``spec`` is not the
            table's spec.
    """
    detected = spec_for(table.name()[-1])
    if spec is not None and spec.name != detected.name:
        raise ValueError(f"spec {spec.name!r} does not belong to table {'.'.join(table.name())}")
    return detected


def _scan(table: Table, row_filter: BooleanExpression, spec: TableSpec) -> pd.DataFrame:
    """Read matching rows from the current snapshot as a frame typed by ``spec``."""
    arrow = table.scan(row_filter=row_filter).to_arrow()
    typed = arrow.select(spec.arrow_schema.names).cast(spec.arrow_schema)
    return typed.to_pandas(types_mapper=pd.ArrowDtype)


def bronze_iceberg_schema(spec: TableSpec = OPTION_CHAIN) -> Schema:
    """Return a bronze table's Iceberg schema, field ids 1 to n in column order.

    Args:
        spec: Which bronze table; the option chain when omitted.

    Returns:
        The Iceberg schema (see ``TableSpec.iceberg_schema``); for the option chain, field
        ids 1 to 20, the strike as ``decimal(10, 3)`` and ``ingested_at`` as ``timestamptz``.
    """
    return spec.iceberg_schema()


def table_identifier(
    env: Mapping[str, str] | None = None, *, spec: TableSpec = OPTION_CHAIN
) -> tuple[str, str]:
    """Return the ``(namespace, table)`` identifier the environment selects.

    The namespace is ``OAP_GLUE_DATABASE`` when ``OAP_ICEBERG_CATALOG`` is ``glue`` and that
    variable is set (for example ``oap_bronze``); otherwise ``bronze``.

    Args:
        env: Environment to read; ``os.environ`` when omitted.
        spec: Which bronze table; the option chain when omitted.

    Returns:
        The identifier, for example ``("bronze", "option_chain")`` or
        ``("oap_bronze", "underlying_price")``.
    """
    env = os.environ if env is None else env
    database = env.get("OAP_GLUE_DATABASE", "").strip()
    if _catalog_kind(env) == "glue" and database:
        return (database, spec.name)
    return (DEFAULT_NAMESPACE, spec.name)


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


def bronze_partition_spec(spec: TableSpec = OPTION_CHAIN) -> PartitionSpec:
    """Return the bronze partition spec: ``day(trade_date)`` then ``identity(source)``.

    Field ids are bound to the table's Iceberg field ids as assigned by ``ensure_table``.

    Args:
        spec: Which bronze table; the option chain when omitted.

    Returns:
        The partition spec, fields named ``trade_date_day`` and ``source``.
    """
    return spec.partition_spec()


def ensure_table(
    catalog: Catalog,
    identifier: tuple[str, str] | None = None,
    *,
    spec: TableSpec | None = None,
) -> Table:
    """Return a bronze table, creating its namespace and the table if missing.

    A new table gets the spec's Iceberg schema and partition spec. An existing table is
    never altered, but it must hold every column of the spec with the same type and
    nullability; a table created by an older contract (for example with a two-decimal
    strike) is reported instead of being written to with a mismatched schema.

    Args:
        catalog: Catalog to create the table in.
        identifier: ``(namespace, table)``. When omitted, ``(DEFAULT_NAMESPACE, spec.name)``.
        spec: Which bronze table. When omitted, detected from the last part of
            ``identifier``; the option chain when both are omitted.

    Returns:
        The loaded table.

    Raises:
        ValueError: If ``identifier`` names another table than ``spec``, its last part is
            not a bronze table, or an existing table's schema differs from the spec; the
            message lists the differing columns.
    """
    if identifier is None:
        spec = OPTION_CHAIN if spec is None else spec
        identifier = (DEFAULT_NAMESPACE, spec.name)
    elif spec is None:
        spec = spec_for(identifier[-1])
    elif identifier[-1] != spec.name:
        raise ValueError(f"identifier {'.'.join(identifier)} is not the table {spec.name!r}")
    catalog.create_namespace_if_not_exists(identifier[0])
    try:
        table = catalog.load_table(identifier)
    except NoSuchTableError:
        try:
            return catalog.create_table(
                identifier, schema=spec.iceberg_schema(), partition_spec=spec.partition_spec()
            )
        except TableAlreadyExistsError:
            table = catalog.load_table(identifier)
    _check_schema(table, spec)
    return table


def _check_schema(table: Table, spec: TableSpec) -> None:
    """Raise ValueError if ``table`` lacks a column of ``spec`` or holds it with another type."""
    actual = {f.name: (f.field_type, f.required) for f in table.schema().fields}
    differences = [
        f"{f.name}: expected {f.field_type}{' required' if f.required else ''}, "
        f"found {actual[f.name][0] if f.name in actual else 'nothing'}"
        for f in spec.iceberg_schema().fields
        if actual.get(f.name) != (f.field_type, f.required)
    ]
    if differences:
        raise ValueError(
            f"table {'.'.join(table.name())} does not match the bronze schema: "
            + "; ".join(differences)
        )


def write_partition(
    table: Table,
    frame: pd.DataFrame,
    *,
    trade_date: date,
    source: str,
    spec: TableSpec | None = None,
) -> int:
    """Replace one (trade_date, source) slice of the table with ``frame``, atomically.

    Validates ``frame`` with the table's pandera schema (``spec.frame_schema.validate(frame,
    lazy=True)``), then commits one overwrite whose filter is
    ``trade_date == trade_date AND source == source``. An empty frame deletes the slice. If
    another writer commits first (``CommitFailedException``), the table is refreshed and the
    overwrite retried, up to ``COMMIT_ATTEMPTS`` times; replacing a slice is idempotent, so a
    retry is safe. Logs one INFO line per write.

    Args:
        table: A bronze table.
        frame: Rows for exactly this slice.
        trade_date: Session date of the slice.
        source: Feed of the slice, one of the table's ``sources``.
        spec: The table's spec, detected from its name when omitted. Passing one that is not
            the table's is an error.

    Returns:
        Number of rows written; 0 for an empty frame.

    Raises:
        ValueError: If ``source`` is not one of the table's sources, ``spec`` is not the
            table's, or any row has a different ``trade_date`` or ``source`` than the slice.
        pandera.errors.SchemaErrors: If ``frame`` breaks the table's contract; every failed
            check is listed. Nothing is committed.
        pyiceberg.exceptions.CommitFailedException: If every attempt lost a commit race.
    """
    spec = _resolve(table, spec)
    if source not in spec.sources:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(spec.sources)}")
    validated = spec.frame_schema.validate(frame, lazy=True)
    other_dates = set(validated["trade_date"]) - {trade_date}
    if other_dates:
        raise ValueError(f"frame holds trade dates {sorted(other_dates)}, slice is {trade_date}")
    other_sources = set(validated["source"]) - {source}
    if other_sources:
        raise ValueError(f"frame holds sources {sorted(other_sources)}, slice is {source!r}")
    arrow = to_arrow(validated, spec.arrow_schema)
    slice_filter = _slice_filter(trade_date, source, spec)
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


def read_partition(
    table: Table, *, trade_date: date, source: str, spec: TableSpec | None = None
) -> pd.DataFrame:
    """Read one (trade_date, source) slice from the current snapshot.

    Args:
        table: A bronze table.
        trade_date: Session date of the slice.
        source: Feed of the slice.
        spec: The table's spec, detected from its name when omitted.

    Returns:
        A frame with the table's columns and dtypes; empty if the slice holds no rows.

    Raises:
        ValueError: If ``source`` is not one of the table's sources or ``spec`` is not the
            table's.
    """
    spec = _resolve(table, spec)
    return _scan(table, _slice_filter(trade_date, source, spec), spec)


def read_range(
    table: Table,
    *,
    start: date,
    end: date,
    source: str | None = None,
    spec: TableSpec | None = None,
) -> pd.DataFrame:
    """Read every row with ``start <= trade_date <= end`` from the current snapshot.

    Args:
        table: A bronze table.
        start: First trade date, inclusive.
        end: Last trade date, inclusive.
        source: Restrict to one feed; every feed when None.
        spec: The table's spec, detected from its name when omitted.

    Returns:
        A frame with the table's columns and dtypes.

    Raises:
        ValueError: If ``start`` is after ``end``, ``source`` is not one of the table's
            sources or ``spec`` is not the table's.
    """
    spec = _resolve(table, spec)
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    text = f"trade_date >= '{start.isoformat()}' AND trade_date <= '{end.isoformat()}'"
    if source is not None:
        text += f" AND source = {_source_literal(source, spec)}"
    return _scan(table, parse_filter(text), spec)


def partition_file_counts(table: Table) -> dict[tuple[date, str], int]:
    """Count live data files per (trade_date, source) slice in the current snapshot.

    Reads the ``partition`` column of ``table.inspect.files()``; this works because
    ``source`` is a partition field, so every data file belongs to exactly one slice. Every
    ``BRONZE_TABLES`` entry names its partition fields alike, so this is valid for each.

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


def content_hash(frame: pd.DataFrame, *, spec: TableSpec = OPTION_CHAIN) -> str:
    """Hash the content of a bronze frame, independent of row order and load time.

    Drops ``ingested_at``, sorts by the spec's key columns (for the option chain
    ``(occ_symbol, trade_date, source)``) and hashes a deterministic serialisation of the
    remaining columns, so two loads of the same data hash equal and any changed value, added
    or removed row changes the hash.

    Args:
        frame: A frame with the spec's columns.
        spec: The frame's table; the option chain when omitted (a frame cannot be detected).

    Returns:
        Lower-case hexadecimal SHA-256 digest, 64 characters.
    """
    columns = [name for name in spec.arrow_schema.names if name != "ingested_at"]
    ordered = frame[columns].sort_values(
        [*spec.key_columns, *(c for c in columns if c not in spec.key_columns)],
        kind="mergesort",
    )
    schema = pa.schema([spec.arrow_schema.field(name) for name in columns])
    rows = pa.Table.from_pandas(ordered, schema=schema, preserve_index=False).to_pylist()
    payload = json.dumps(rows, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
