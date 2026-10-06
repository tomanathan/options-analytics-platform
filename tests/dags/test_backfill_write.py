from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pyiceberg.table import Table

from dags.backfill_chains import merge_into_slices
from oap.ingest.iceberg_writer import (
    catalog_from_env,
    content_hash,
    ensure_table,
    read_partition,
    write_partition,
)
from tests.bronze_factory import bronze_frame

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)


@pytest.fixture
def table(tmp_path: Path) -> Table:
    catalog = catalog_from_env(
        {
            "OAP_ICEBERG_CATALOG": "sql",
            "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/catalog.db",
            "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/warehouse",
        }
    )
    return ensure_table(catalog)


def _seed(table: Table) -> None:
    for day in (D1, D2):
        frame = bronze_frame(day, underlyings=("SPY", "QQQ"), rows_per_underlying=4)
        write_partition(table, frame, trade_date=day, source="dolthub")


def _spy(day: date, seed: int) -> pd.DataFrame:
    return bronze_frame(day, underlyings=("SPY",), rows_per_underlying=6, seed=seed)


def _by_underlying(table: Table, day: date) -> dict[str, int]:
    frame = read_partition(table, trade_date=day, source="dolthub")
    return {str(k): int(v) for k, v in frame.groupby("underlying", observed=True).size().items()}


def test_loading_one_symbol_keeps_the_other_symbols_of_the_slice(table: Table) -> None:
    _seed(table)
    fetched = pd.concat([_spy(D1, seed=1), _spy(D2, seed=1)], ignore_index=True)

    counts = merge_into_slices(table, fetched, symbols=["SPY"], sessions=[D1, D2])

    assert counts == {"days": 2, "unchanged": 0, "rows": 20}
    assert _by_underlying(table, D1) == {"QQQ": 4, "SPY": 6}
    spy = read_partition(table, trade_date=D1, source="dolthub")
    assert content_hash(spy[spy["underlying"] == "SPY"]) == content_hash(_spy(D1, seed=1))


def test_reloading_the_same_data_commits_nothing(table: Table) -> None:
    _seed(table)
    fetched = pd.concat([_spy(D1, seed=1), _spy(D2, seed=1)], ignore_index=True)
    merge_into_slices(table, fetched, symbols=["SPY"], sessions=[D1, D2])
    snapshots = len(table.refresh().metadata.snapshots)

    counts = merge_into_slices(table, fetched, symbols=["SPY"], sessions=[D1, D2])

    assert counts == {"days": 0, "unchanged": 2, "rows": 0}
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_a_day_without_fetched_rows_drops_only_the_requested_symbols(table: Table) -> None:
    _seed(table)

    counts = merge_into_slices(table, _spy(D1, seed=1), symbols=["SPY"], sessions=[D1, D2])

    assert counts["days"] == 2
    assert _by_underlying(table, D2) == {"QQQ": 4}


def test_nothing_fetched_into_an_empty_table_writes_nothing(table: Table) -> None:
    assert merge_into_slices(table, None, symbols=["SPY"], sessions=[D1, D2]) == {
        "days": 0,
        "unchanged": 2,
        "rows": 0,
    }


def test_staged_parquet_round_trips_into_a_valid_bronze_write(table: Table, tmp_path: Path) -> None:
    # fetch_month stages with to_parquet and write_month reads with dtype_backend="pyarrow".
    path = tmp_path / "SPY.parquet"
    _spy(D1, seed=3).to_parquet(path, index=False)
    staged = pd.read_parquet(path, dtype_backend="pyarrow")

    assert merge_into_slices(table, staged, symbols=["SPY"], sessions=[D1])["rows"] == 6
    assert content_hash(read_partition(table, trade_date=D1, source="dolthub")) == content_hash(
        _spy(D1, seed=3)
    )
