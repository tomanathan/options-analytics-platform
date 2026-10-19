from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest
from airflow.exceptions import AirflowFailException
from pyiceberg.table import Table

from dags import backfill_chains
from oap.ingest.iceberg_writer import (
    catalog_from_env,
    content_hash,
    ensure_table,
    read_partition,
    write_partition,
)
from tests.bronze_factory import INGESTED_AT, bronze_frame

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
JANUARY = {"month": "2024-01", "start": "2024-01-02", "end": "2024-01-31"}

WriteMonth = Callable[[dict[str, Any]], dict[str, Any]]


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


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    return tmp_path / "staging"


@pytest.fixture
def write_month(table: Table, staging: Path, monkeypatch: pytest.MonkeyPatch) -> WriteMonth:
    """The write_month task callable, wired to the test table and a test staging dir."""
    monkeypatch.setattr(backfill_chains, "bronze_table", lambda: table)
    monkeypatch.setattr(backfill_chains, "staging_dir", lambda *parts: staging)
    monkeypatch.setattr(backfill_chains, "get_current_context", lambda: {"run_id": "test"})
    task = backfill_chains.backfill_chains().get_task("write_month")
    return cast(WriteMonth, cast(Any, task).python_callable)


def _seed(table: Table) -> None:
    for day in (D1, D2):
        frame = bronze_frame(day, underlyings=("SPY", "QQQ"), rows_per_underlying=4)
        write_partition(table, frame, trade_date=day, source="dolthub")


def _spy(day: date, seed: int) -> pd.DataFrame:
    return bronze_frame(day, underlyings=("SPY",), rows_per_underlying=6, seed=seed)


def _stage(staging: Path, frame: pd.DataFrame | None, symbol: str) -> None:
    """Stage a symbol's fetch the way fetch_month does: a parquet file, or an empty marker."""
    staging.mkdir(exist_ok=True)
    if frame is None:
        (staging / f"{symbol}.empty").touch()
    else:
        frame.to_parquet(staging / f"{symbol}.parquet", index=False)


def _by_underlying(table: Table, day: date) -> dict[str, int]:
    frame = read_partition(table, trade_date=day, source="dolthub")
    return {str(k): int(v) for k, v in frame.groupby("underlying", observed=True).size().items()}


def test_loading_one_symbol_keeps_the_other_symbols_of_the_slice(
    table: Table, staging: Path, write_month: WriteMonth
) -> None:
    _seed(table)
    _stage(staging, pd.concat([_spy(D1, 1), _spy(D2, 1)], ignore_index=True), "SPY")

    result = write_month({**JANUARY, "symbols": ["SPY"]})

    assert result == {"month": "2024-01", "days": 2, "unchanged": 0, "rows": 20}
    assert _by_underlying(table, D1) == {"QQQ": 4, "SPY": 6}
    stored = read_partition(table, trade_date=D1, source="dolthub")
    assert content_hash(stored[stored["underlying"] == "SPY"]) == content_hash(_spy(D1, 1))


def test_rerunning_the_same_month_commits_nothing(
    table: Table, staging: Path, write_month: WriteMonth
) -> None:
    _seed(table)
    fetched = pd.concat([_spy(D1, 1), _spy(D2, 1)], ignore_index=True)
    _stage(staging, fetched, "SPY")
    write_month({**JANUARY, "symbols": ["SPY"]})
    snapshots = len(table.refresh().metadata.snapshots)
    _stage(staging, fetched, "SPY")

    result = write_month({**JANUARY, "symbols": ["SPY"]})

    assert result == {"month": "2024-01", "days": 0, "unchanged": 2, "rows": 0}
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_written_rows_are_stamped_when_the_slice_is_written(
    table: Table, staging: Path, write_month: WriteMonth
) -> None:
    _stage(staging, _spy(D1, 1), "SPY")
    before = datetime.now(UTC)

    write_month({**JANUARY, "symbols": ["SPY"]})

    stamps = read_partition(table, trade_date=D1, source="dolthub")["ingested_at"]
    assert (stamps > pd.Timestamp(INGESTED_AT)).all()
    assert (stamps >= pd.Timestamp(before)).all()


def test_an_empty_fetch_leaves_that_symbols_rows_untouched(
    table: Table, staging: Path, write_month: WriteMonth
) -> None:
    _seed(table)
    qqq_before = read_partition(table, trade_date=D1, source="dolthub")
    qqq_before = qqq_before[qqq_before["underlying"] == "QQQ"]
    _stage(staging, _spy(D1, 1), "SPY")
    _stage(staging, None, "QQQ")

    result = write_month({**JANUARY, "symbols": ["SPY", "QQQ"]})

    assert result == {"month": "2024-01", "days": 1, "unchanged": 0, "rows": 10}
    after = read_partition(table, trade_date=D1, source="dolthub")
    assert content_hash(after[after["underlying"] == "QQQ"]) == content_hash(qqq_before)
    assert _by_underlying(table, D2) == {"QQQ": 4, "SPY": 4}


def test_every_fetch_empty_writes_nothing(
    table: Table, staging: Path, write_month: WriteMonth
) -> None:
    _seed(table)
    snapshots = len(table.refresh().metadata.snapshots)
    _stage(staging, None, "SPY")

    result = write_month({**JANUARY, "symbols": ["SPY"]})

    assert result == {"month": "2024-01", "days": 0, "unchanged": 0, "rows": 0}
    assert _by_underlying(table, D1) == {"QQQ": 4, "SPY": 4}
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_a_failed_fetch_fails_the_month_without_writing(
    table: Table, staging: Path, write_month: WriteMonth
) -> None:
    _seed(table)
    _stage(staging, _spy(D1, 1), "SPY")

    with pytest.raises(AirflowFailException, match="QQQ"):
        write_month({**JANUARY, "symbols": ["SPY", "QQQ"]})
    assert _by_underlying(table, D1) == {"QQQ": 4, "SPY": 4}


def test_the_dag_has_no_private_copy_of_the_merge() -> None:
    assert not hasattr(backfill_chains, "merge_into_slices")
    assert not hasattr(backfill_chains, "merge_day")
