from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest
from airflow.exceptions import AirflowFailException
from pyiceberg.table import Table

from dags import backfill_chains
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

    counts = merge_into_slices(table, fetched)

    assert counts == {"days": 2, "unchanged": 0, "rows": 20}
    assert _by_underlying(table, D1) == {"QQQ": 4, "SPY": 6}
    spy = read_partition(table, trade_date=D1, source="dolthub")
    assert content_hash(spy[spy["underlying"] == "SPY"]) == content_hash(_spy(D1, seed=1))


def test_reloading_the_same_data_commits_nothing(table: Table) -> None:
    _seed(table)
    fetched = pd.concat([_spy(D1, seed=1), _spy(D2, seed=1)], ignore_index=True)
    merge_into_slices(table, fetched)
    snapshots = len(table.refresh().metadata.snapshots)

    counts = merge_into_slices(table, fetched)

    assert counts == {"days": 0, "unchanged": 2, "rows": 0}
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_a_symbol_without_rows_on_a_day_keeps_its_rows_for_that_day(table: Table) -> None:
    _seed(table)
    before = content_hash(read_partition(table, trade_date=D2, source="dolthub"))

    counts = merge_into_slices(table, _spy(D1, seed=1))

    assert counts == {"days": 1, "unchanged": 0, "rows": 10}
    assert _by_underlying(table, D1) == {"QQQ": 4, "SPY": 6}
    assert content_hash(read_partition(table, trade_date=D2, source="dolthub")) == before


def test_nothing_fetched_writes_nothing(table: Table) -> None:
    _seed(table)
    snapshots = len(table.refresh().metadata.snapshots)

    assert merge_into_slices(table, None) == {"days": 0, "unchanged": 0, "rows": 0}
    assert merge_into_slices(table, _spy(D1, seed=1).iloc[0:0]) == {
        "days": 0,
        "unchanged": 0,
        "rows": 0,
    }
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_staged_parquet_round_trips_into_a_valid_bronze_write(table: Table, tmp_path: Path) -> None:
    # fetch_month stages with to_parquet and write_month reads with dtype_backend="pyarrow".
    path = tmp_path / "SPY.parquet"
    _spy(D1, seed=3).to_parquet(path, index=False)
    staged = pd.read_parquet(path, dtype_backend="pyarrow")

    assert merge_into_slices(table, staged)["rows"] == 6
    assert content_hash(read_partition(table, trade_date=D1, source="dolthub")) == content_hash(
        _spy(D1, seed=3)
    )


@pytest.fixture
def write_month(
    table: Table, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """The write_month task callable, wired to the test table and a test staging dir."""
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(backfill_chains, "bronze_table", lambda: table)
    monkeypatch.setattr(backfill_chains, "staging_dir", lambda *parts: staging)
    monkeypatch.setattr(backfill_chains, "get_current_context", lambda: {"run_id": "test"})
    task = backfill_chains.backfill_chains().get_task("write_month")
    return cast(Callable[[dict[str, Any]], dict[str, Any]], cast(Any, task).python_callable)


def _stage(tmp_path: Path, frame: pd.DataFrame | None, symbol: str) -> None:
    staging = tmp_path / "staging"
    if frame is None:
        (staging / f"{symbol}.empty").touch()
    else:
        frame.to_parquet(staging / f"{symbol}.parquet", index=False)


JANUARY = {"month": "2024-01", "start": "2024-01-02", "end": "2024-01-31"}


def test_an_empty_fetch_leaves_that_symbols_rows_untouched(
    table: Table, tmp_path: Path, write_month: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    _seed(table)
    qqq_before = read_partition(table, trade_date=D1, source="dolthub")
    qqq_before = qqq_before[qqq_before["underlying"] == "QQQ"]
    _stage(tmp_path, _spy(D1, seed=1), "SPY")
    _stage(tmp_path, None, "QQQ")

    result = write_month({**JANUARY, "symbols": ["SPY", "QQQ"]})

    assert result == {"month": "2024-01", "days": 1, "unchanged": 0, "rows": 10}
    after = read_partition(table, trade_date=D1, source="dolthub")
    assert content_hash(after[after["underlying"] == "QQQ"]) == content_hash(qqq_before)
    assert _by_underlying(table, D2) == {"QQQ": 4, "SPY": 4}


def test_every_fetch_empty_writes_nothing(
    table: Table, tmp_path: Path, write_month: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    _seed(table)
    _stage(tmp_path, None, "SPY")

    result = write_month({**JANUARY, "symbols": ["SPY"]})

    assert result == {"month": "2024-01", "days": 0, "unchanged": 0, "rows": 0}
    assert _by_underlying(table, D1) == {"QQQ": 4, "SPY": 4}


def test_a_failed_fetch_fails_the_month_without_writing(
    table: Table, tmp_path: Path, write_month: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    _seed(table)
    _stage(tmp_path, _spy(D1, seed=1), "SPY")

    with pytest.raises(AirflowFailException, match="QQQ"):
        write_month({**JANUARY, "symbols": ["SPY", "QQQ"]})
    assert _by_underlying(table, D1) == {"QQQ": 4, "SPY": 4}
