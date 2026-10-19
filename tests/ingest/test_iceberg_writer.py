import logging
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.errors
import pytest
from pyiceberg.catalog import Catalog
from pyiceberg.catalog.glue import GlueCatalog
from pyiceberg.exceptions import CommitFailedException
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import DayTransform, IdentityTransform
from pyiceberg.types import DateType, DecimalType, NestedField, TimestamptzType

from oap.ingest.alpaca import parse_snapshots
from oap.ingest.iceberg_writer import (
    TABLE_IDENTIFIER,
    bronze_iceberg_schema,
    catalog_from_env,
    content_hash,
    ensure_table,
    partition_file_counts,
    read_partition,
    read_range,
    table_identifier,
    write_partition,
)
from oap.ingest.local_catalog import LocalCatalog
from oap.ingest.schema import BRONZE_FRAME, BRONZE_SCHEMA, empty_frame, to_arrow
from oap.ingest.tables import BRONZE_TABLES, OPTION_CHAIN, UNDERLYING_PRICE, TableSpec
from tests.bronze_factory import bronze_frame
from tests.ingest.price_factory import price_frame

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
D3 = date(2024, 1, 4)
LATER = datetime(2024, 1, 5, 22, 0, tzinfo=UTC)


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    return catalog_from_env(
        {
            "OAP_ICEBERG_CATALOG": "sql",
            "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/catalog.db",
            "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/warehouse",
        }
    )


@pytest.fixture
def table(catalog: Catalog) -> Table:
    return ensure_table(catalog)


def _dolthub(day: date, rows: int = 10, seed: int = 0) -> pd.DataFrame:
    return bronze_frame(day, underlyings=("SPY", "QQQ"), rows_per_underlying=rows, seed=seed)


def _alpaca(day: date, rows: int = 6) -> pd.DataFrame:
    return bronze_frame(day, rows_per_underlying=rows, source="alpaca_indicative", seed=7)


def _row_count(table: Table) -> int:
    return len(table.scan().to_arrow())


# catalog and identifier


def test_catalog_from_env_defaults_to_a_local_sql_catalog_under_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    catalog = catalog_from_env({})

    assert list(tmp_path.iterdir()) == []
    ensure_table(catalog)
    assert (tmp_path / ".iceberg-local" / "catalog.db").is_file()
    assert catalog.list_tables("bronze") == [TABLE_IDENTIFIER]


def test_catalog_from_env_has_no_side_effects(tmp_path: Path) -> None:
    env = {
        "OAP_ICEBERG_CATALOG": "sql",
        "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/nested/dir/catalog.db",
        "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/warehouse",
    }

    catalog_from_env(env)

    assert list(tmp_path.iterdir()) == []


def test_catalog_from_env_resolves_relative_local_paths_against_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The form .env.example documents: relative SQLite URI and file:// warehouse.
    monkeypatch.chdir(tmp_path)
    env = {
        "OAP_ICEBERG_CATALOG": "sql",
        "OAP_ICEBERG_URI": "sqlite:///.iceberg-local/catalog.db",
        "OAP_ICEBERG_WAREHOUSE": "file://./.iceberg-local/warehouse",
    }

    table = ensure_table(catalog_from_env(env))
    write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub")

    assert (tmp_path / ".iceberg-local" / "catalog.db").is_file()
    assert list((tmp_path / ".iceberg-local" / "warehouse").rglob("*.parquet"))


def test_catalog_from_env_rejects_an_unknown_catalog() -> None:
    with pytest.raises(ValueError):
        catalog_from_env({"OAP_ICEBERG_CATALOG": "hive"})


@pytest.mark.parametrize("warehouse", [None, "file:///tmp/warehouse"])
def test_catalog_from_env_glue_requires_an_s3_warehouse(warehouse: str | None) -> None:
    env = {"OAP_ICEBERG_CATALOG": "glue", "AWS_REGION": "us-east-1"}
    if warehouse is not None:
        env["OAP_ICEBERG_WAREHOUSE"] = warehouse

    with pytest.raises(ValueError):
        catalog_from_env(env)


def test_catalog_from_env_builds_a_glue_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    env = {
        "OAP_ICEBERG_CATALOG": "glue",
        "OAP_ICEBERG_WAREHOUSE": "s3://oap-test-bucket/bronze",
        "AWS_REGION": "us-east-1",
    }

    assert isinstance(catalog_from_env(env), GlueCatalog)


def test_table_identifier_defaults_to_bronze() -> None:
    assert table_identifier({}) == ("bronze", "option_chain")
    assert TABLE_IDENTIFIER == ("bronze", "option_chain")


def test_table_identifier_uses_the_glue_database_on_glue() -> None:
    env = {"OAP_ICEBERG_CATALOG": "glue", "OAP_GLUE_DATABASE": "oap_bronze"}

    assert table_identifier(env) == ("oap_bronze", "option_chain")


def test_table_identifier_ignores_the_glue_database_on_sql() -> None:
    env = {"OAP_ICEBERG_CATALOG": "sql", "OAP_GLUE_DATABASE": "oap_bronze"}

    assert table_identifier(env) == ("bronze", "option_chain")


# ensure_table


def test_ensure_table_is_idempotent(catalog: Catalog) -> None:
    first = ensure_table(catalog)
    second = ensure_table(catalog)

    assert first.metadata_location == second.metadata_location
    assert catalog.list_tables("bronze") == [TABLE_IDENTIFIER]


def test_ensure_table_does_not_touch_existing_data(catalog: Catalog) -> None:
    write_partition(ensure_table(catalog), _dolthub(D1), trade_date=D1, source="dolthub")

    assert _row_count(ensure_table(catalog)) == 20


def test_ensure_table_rejects_a_table_from_an_older_contract(catalog: Catalog) -> None:
    old_fields = [
        NestedField(f.field_id, f.name, DecimalType(10, 2), required=f.required)
        if f.name == "strike"
        else f
        for f in bronze_iceberg_schema().fields
    ]
    catalog.create_namespace("bronze")
    catalog.create_table(TABLE_IDENTIFIER, schema=Schema(*old_fields))

    with pytest.raises(ValueError, match=r"strike: expected decimal\(10, 3\)"):
        ensure_table(catalog)


def test_ensure_table_schema_matches_bronze_schema(table: Table) -> None:
    schema = table.schema()

    assert [f.name for f in schema.fields] == BRONZE_SCHEMA.names
    required = {f.name for f in schema.fields if f.required}
    assert required == {f.name for f in BRONZE_SCHEMA if not f.nullable}
    assert schema.find_field("trade_date").field_type == DateType()
    assert schema.find_field("strike").field_type == DecimalType(10, 3)
    assert schema.find_field("ingested_at").field_type == TimestamptzType()


def test_ensure_table_partitions_by_day_of_trade_date_and_source(table: Table) -> None:
    schema = table.schema()
    fields = [
        (schema.find_column_name(f.source_id), type(f.transform), f.name)
        for f in table.spec().fields
    ]

    assert fields == [
        ("trade_date", DayTransform, "trade_date_day"),
        ("source", IdentityTransform, "source"),
    ]


# write_partition


def test_write_partition_returns_the_row_count(table: Table) -> None:
    assert write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub") == 20


def test_writing_the_same_frame_twice_changes_nothing(table: Table) -> None:
    frame = _dolthub(D1)

    write_partition(table, frame, trade_date=D1, source="dolthub")
    first = content_hash(read_partition(table, trade_date=D1, source="dolthub"))
    write_partition(table, frame, trade_date=D1, source="dolthub")
    second = content_hash(read_partition(table, trade_date=D1, source="dolthub"))

    assert _row_count(table) == len(frame)
    assert first == second == content_hash(frame)


def test_reloading_with_a_new_ingested_at_keeps_the_content_hash(table: Table) -> None:
    write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub")
    reload = bronze_frame(D1, underlyings=("SPY", "QQQ"), rows_per_underlying=10, ingested_at=LATER)
    write_partition(table, reload, trade_date=D1, source="dolthub")

    stored = read_partition(table, trade_date=D1, source="dolthub")
    assert len(stored) == 20
    assert content_hash(stored) == content_hash(_dolthub(D1))
    assert (stored["ingested_at"] == LATER).all()


def test_a_different_frame_fully_replaces_the_slice(table: Table) -> None:
    write_partition(table, _dolthub(D1, rows=10), trade_date=D1, source="dolthub")
    replacement = _dolthub(D1, rows=3, seed=99)

    written = write_partition(table, replacement, trade_date=D1, source="dolthub")

    stored = read_partition(table, trade_date=D1, source="dolthub")
    assert written == 6
    assert len(stored) == 6
    assert content_hash(stored) == content_hash(replacement)


def test_two_sources_on_the_same_date_coexist(table: Table) -> None:
    dolthub, alpaca = _dolthub(D1), _alpaca(D1)
    write_partition(table, dolthub, trade_date=D1, source="dolthub")
    write_partition(table, alpaca, trade_date=D1, source="alpaca_indicative")

    write_partition(table, _dolthub(D1, rows=2, seed=5), trade_date=D1, source="dolthub")

    assert content_hash(read_partition(table, trade_date=D1, source="alpaca_indicative")) == (
        content_hash(alpaca)
    )
    assert _row_count(table) == 4 + len(alpaca)


def test_writing_one_date_leaves_other_dates_untouched(table: Table) -> None:
    other = _dolthub(D2, seed=3)
    write_partition(table, other, trade_date=D2, source="dolthub")

    write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub")
    write_partition(table, _dolthub(D1, seed=4), trade_date=D1, source="dolthub")

    assert content_hash(read_partition(table, trade_date=D2, source="dolthub")) == (
        content_hash(other)
    )


def test_write_partition_rejects_a_frame_with_another_trade_date(table: Table) -> None:
    with pytest.raises(ValueError):
        write_partition(table, _dolthub(D1), trade_date=D2, source="dolthub")
    assert _row_count(table) == 0


def test_write_partition_rejects_a_frame_with_another_source(table: Table) -> None:
    with pytest.raises(ValueError):
        write_partition(table, _alpaca(D1), trade_date=D1, source="dolthub")
    assert _row_count(table) == 0


def test_write_partition_rejects_an_unknown_source(table: Table) -> None:
    with pytest.raises(ValueError):
        write_partition(table, empty_frame(), trade_date=D1, source="yahoo")


def test_write_partition_rejects_a_frame_that_breaks_the_contract(table: Table) -> None:
    frame = _dolthub(D1)
    frame.loc[0, "bid"] = 99.0
    frame.loc[0, "ask"] = 1.0

    with pytest.raises(pandera.errors.SchemaErrors):
        write_partition(table, frame, trade_date=D1, source="dolthub")
    assert _row_count(table) == 0


def test_an_empty_frame_removes_the_slice(table: Table) -> None:
    write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub")
    write_partition(table, _alpaca(D1), trade_date=D1, source="alpaca_indicative")

    written = write_partition(table, empty_frame(), trade_date=D1, source="dolthub")

    assert written == 0
    assert len(read_partition(table, trade_date=D1, source="dolthub")) == 0
    assert (D1, "dolthub") not in partition_file_counts(table)
    assert len(read_partition(table, trade_date=D1, source="alpaca_indicative")) == 6


def test_every_write_is_a_snapshot_and_replaced_data_stays_readable(table: Table) -> None:
    original = _dolthub(D1)
    write_partition(table, original, trade_date=D1, source="dolthub")
    first_snapshot = table.current_snapshot()
    assert first_snapshot is not None

    write_partition(table, _dolthub(D1, rows=1, seed=8), trade_date=D1, source="dolthub")

    old = table.scan(snapshot_id=first_snapshot.snapshot_id).to_pandas(types_mapper=pd.ArrowDtype)
    assert content_hash(old[BRONZE_SCHEMA.names]) == content_hash(original)
    assert len(read_partition(table, trade_date=D1, source="dolthub")) == 2


# reads


def test_read_partition_returns_a_bronze_frame(table: Table) -> None:
    frame = _dolthub(D1)
    write_partition(table, frame, trade_date=D1, source="dolthub")

    stored = read_partition(table, trade_date=D1, source="dolthub")

    assert list(stored.columns) == BRONZE_SCHEMA.names
    for field in BRONZE_SCHEMA:
        assert stored[field.name].dtype == pd.ArrowDtype(field.type), field.name
    BRONZE_FRAME.validate(stored)


def test_read_partition_of_a_missing_slice_is_empty(table: Table) -> None:
    stored = read_partition(table, trade_date=D3, source="dolthub")

    assert len(stored) == 0
    assert list(stored.columns) == BRONZE_SCHEMA.names


def test_read_range_filters_dates_inclusively_and_by_source(table: Table) -> None:
    for day in (D1, D2, D3):
        write_partition(table, _dolthub(day), trade_date=day, source="dolthub")
    write_partition(table, _alpaca(D2), trade_date=D2, source="alpaca_indicative")

    both = read_range(table, start=D1, end=D2)
    dolthub_only = read_range(table, start=D1, end=D2, source="dolthub")
    one_day = read_range(table, start=D3, end=D3)

    assert set(both["trade_date"]) == {D1, D2}
    assert len(both) == 20 + 20 + 6
    assert set(dolthub_only["source"]) == {"dolthub"}
    assert len(dolthub_only) == 40
    assert set(one_day["trade_date"]) == {D3}


def test_read_range_rejects_an_inverted_range(table: Table) -> None:
    with pytest.raises(ValueError):
        read_range(table, start=D2, end=D1)


# partition_file_counts


def test_partition_file_counts_of_an_empty_table(table: Table) -> None:
    assert partition_file_counts(table) == {}


def test_rewriting_a_slice_leaves_one_file(table: Table) -> None:
    # Verified on pyiceberg 0.12: overwrite drops the slice's old file and appends one new
    # file, so repeated loads do not accumulate files.
    write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub")
    write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub")
    write_partition(table, _alpaca(D1), trade_date=D1, source="alpaca_indicative")
    write_partition(table, _dolthub(D2), trade_date=D2, source="dolthub")

    assert partition_file_counts(table) == {
        (D1, "dolthub"): 1,
        (D1, "alpaca_indicative"): 1,
        (D2, "dolthub"): 1,
    }


# content_hash


def test_content_hash_is_a_sha256_hex_digest() -> None:
    digest = content_hash(_dolthub(D1))

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_content_hash_ignores_row_order_and_index() -> None:
    frame = _dolthub(D1)
    shuffled = frame.sample(frac=1, random_state=1)

    assert content_hash(shuffled) == content_hash(frame)


def test_content_hash_ignores_ingested_at() -> None:
    later = bronze_frame(D1, underlyings=("SPY", "QQQ"), rows_per_underlying=10, ingested_at=LATER)

    assert content_hash(later) == content_hash(_dolthub(D1))


def test_content_hash_changes_with_any_value() -> None:
    frame = _dolthub(D1)
    changed = frame.copy()
    changed.loc[3, "bid"] = 0.01  # factory bids start at 0.05

    assert content_hash(changed) != content_hash(frame)


def test_content_hash_changes_when_a_row_is_removed() -> None:
    frame = _dolthub(D1)

    assert content_hash(frame.iloc[1:]) != content_hash(frame)


def test_content_hash_of_an_empty_frame_is_stable() -> None:
    assert content_hash(empty_frame()) == content_hash(empty_frame())


# catalog kinds, import side effects, concurrency


@pytest.mark.parametrize("kind", ["sql", "local", "LOCAL"])
def test_local_kinds_build_a_local_catalog(tmp_path: Path, kind: str) -> None:
    env = {
        "OAP_ICEBERG_CATALOG": kind,
        "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/catalog.db",
        "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/warehouse",
    }

    assert isinstance(catalog_from_env(env), LocalCatalog)


def test_importing_the_writer_creates_no_directories(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-c", "import oap.ingest.iceberg_writer"], cwd=tmp_path, check=True
    )

    assert list(tmp_path.iterdir()) == []


def test_write_partition_retries_when_another_writer_commits_first(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = table.catalog
    commit = catalog.commit_table
    calls: list[int] = []

    def lose_first_race(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise CommitFailedException("another writer committed first")
        return commit(*args, **kwargs)

    monkeypatch.setattr(catalog, "commit_table", lose_first_race)

    written = write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub")

    assert written == 20
    assert len(calls) >= 2
    assert content_hash(read_partition(table, trade_date=D1, source="dolthub")) == (
        content_hash(_dolthub(D1))
    )


def test_write_partition_logs_the_slice(table: Table, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="oap.ingest.iceberg_writer"):
        write_partition(table, _dolthub(D1), trade_date=D1, source="dolthub")

    lines = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO and r.name == "oap.ingest.iceberg_writer"
    ]
    assert any("dolthub" in line and "2024-01-02" in line and "20 rows" in line for line in lines)


def test_reads_reject_an_unknown_source(table: Table) -> None:
    with pytest.raises(ValueError):
        read_partition(table, trade_date=D1, source="x' OR '1'='1")
    with pytest.raises(ValueError):
        read_range(table, start=D1, end=D2, source="yahoo")


def test_a_three_decimal_strike_round_trips_through_bronze(table: Table) -> None:
    # Adjusted contracts after splits carry thousandths, as the OCC code does.
    as_of = date(2026, 10, 5)
    quote = {"t": "2026-10-05T19:59:59Z", "bp": 1.10, "bs": 1, "ap": 1.20, "as": 1}
    payload = {"snapshots": {"SPY261016C00012625": {"latestQuote": quote}}}
    frame = parse_snapshots(
        payload,
        underlying="SPY",
        as_of=as_of,
        underlying_price=None,
        ingested_at=LATER,
    )

    assert to_arrow(frame).column("strike").to_pylist() == [Decimal("12.625")]
    write_partition(table, frame, trade_date=as_of, source="alpaca_indicative")

    stored = read_partition(table, trade_date=as_of, source="alpaca_indicative")
    assert stored["strike"].tolist() == [Decimal("12.625")]
    assert stored["occ_symbol"].tolist() == ["SPY261016C00012625"]


# the second table: bronze.underlying_price


def _prices(
    day: date, underlyings: tuple[str, ...] = ("SPY", "QQQ"), seed: int = 0
) -> pd.DataFrame:
    return price_frame(day, underlyings, seed)


def test_both_tables_coexist_in_one_catalog(catalog: Catalog) -> None:
    ensure_table(catalog, spec=UNDERLYING_PRICE)
    ensure_table(catalog)

    assert sorted(catalog.list_tables("bronze")) == [
        ("bronze", "option_chain"),
        ("bronze", "underlying_price"),
    ]


def test_ensure_table_detects_the_spec_from_the_identifier(catalog: Catalog) -> None:
    table = ensure_table(catalog, ("bronze", "underlying_price"))

    assert len(table.schema().fields) == len(UNDERLYING_PRICE.arrow_schema) == 9
    assert [field.name for field in table.spec().fields] == ["trade_date_day", "source"]


def test_ensure_table_rejects_a_mismatched_spec_and_identifier(catalog: Catalog) -> None:
    with pytest.raises(ValueError, match="underlying_price"):
        ensure_table(catalog, ("bronze", "option_chain"), spec=UNDERLYING_PRICE)


def test_ensure_table_rejects_a_name_that_is_not_a_bronze_table(catalog: Catalog) -> None:
    with pytest.raises(ValueError, match="no bronze table named"):
        ensure_table(catalog, ("bronze", "quotes"))


def test_ensure_table_reports_a_price_table_with_another_schema(catalog: Catalog) -> None:
    catalog.create_namespace_if_not_exists("bronze")
    catalog.create_table(
        ("bronze", "underlying_price"),
        schema=Schema(NestedField(1, "trade_date", DateType(), required=True)),
    )

    with pytest.raises(ValueError, match="does not match the bronze schema"):
        ensure_table(catalog, spec=UNDERLYING_PRICE)


def test_price_write_round_trip_and_idempotence(catalog: Catalog) -> None:
    table = ensure_table(catalog, spec=UNDERLYING_PRICE)
    frame = _prices(D1)

    assert write_partition(table, frame, trade_date=D1, source="dolthub_stocks") == 2
    stored = read_partition(table, trade_date=D1, source="dolthub_stocks")
    first = content_hash(stored, spec=UNDERLYING_PRICE)

    assert first == content_hash(frame, spec=UNDERLYING_PRICE)
    assert list(stored.columns) == UNDERLYING_PRICE.arrow_schema.names
    write_partition(table, frame, trade_date=D1, source="dolthub_stocks")
    again = read_partition(table, trade_date=D1, source="dolthub_stocks")
    assert content_hash(again, spec=UNDERLYING_PRICE) == first
    assert len(read_range(table, start=D1, end=D1, spec=UNDERLYING_PRICE)) == 2


def test_price_content_hash_changes_with_a_close() -> None:
    frame = _prices(D1)
    changed = frame.assign(close=frame["close"] + 0.01)

    assert content_hash(changed, spec=UNDERLYING_PRICE) != content_hash(
        frame, spec=UNDERLYING_PRICE
    )


def test_write_partition_rejects_a_spec_that_is_not_the_tables(catalog: Catalog) -> None:
    table = ensure_table(catalog, spec=UNDERLYING_PRICE)

    with pytest.raises(ValueError, match="does not belong"):
        write_partition(
            table, _prices(D1), trade_date=D1, source="dolthub_stocks", spec=OPTION_CHAIN
        )
    with pytest.raises(ValueError, match="does not belong"):
        read_partition(table, trade_date=D1, source="dolthub_stocks", spec=OPTION_CHAIN)
    assert _row_count(table) == 0


def test_write_partition_rejects_an_option_source_on_the_price_table(catalog: Catalog) -> None:
    table = ensure_table(catalog, spec=UNDERLYING_PRICE)

    with pytest.raises(ValueError, match="unknown source"):
        write_partition(table, _prices(D1), trade_date=D1, source="dolthub")
    with pytest.raises(ValueError, match="unknown source"):
        read_range(table, start=D1, end=D1, source="alpaca_indicative")
    assert _row_count(table) == 0


def test_write_partition_rejects_a_price_frame_with_another_source(catalog: Catalog) -> None:
    table = ensure_table(catalog, spec=UNDERLYING_PRICE)

    with pytest.raises(pandera.errors.SchemaErrors):
        write_partition(
            table, _prices(D1).assign(source="dolthub"), trade_date=D1, source="dolthub_stocks"
        )


def test_partition_file_counts_per_table(catalog: Catalog) -> None:
    options = ensure_table(catalog)
    prices = ensure_table(catalog, spec=UNDERLYING_PRICE)
    write_partition(options, _dolthub(D1), trade_date=D1, source="dolthub")
    write_partition(prices, _prices(D1), trade_date=D1, source="dolthub_stocks")
    write_partition(prices, _prices(D1), trade_date=D1, source="dolthub_stocks")

    assert partition_file_counts(options) == {(D1, "dolthub"): 1}
    assert partition_file_counts(prices) == {(D1, "dolthub_stocks"): 1}


def test_table_identifier_for_prices_on_glue() -> None:
    env = {"OAP_ICEBERG_CATALOG": "glue", "OAP_GLUE_DATABASE": "oap_bronze"}

    assert table_identifier(env, spec=UNDERLYING_PRICE) == ("oap_bronze", "underlying_price")
    assert table_identifier({}, spec=UNDERLYING_PRICE) == ("bronze", "underlying_price")
    assert table_identifier({}) == ("bronze", "option_chain")


@pytest.mark.parametrize("spec", BRONZE_TABLES, ids=lambda spec: spec.name)
def test_table_identifier_names_every_bronze_table(spec: TableSpec) -> None:
    assert table_identifier({}, spec=spec) == ("bronze", spec.name)
