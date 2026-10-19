from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.models import DagBag
from pyiceberg.table import Table

from dags import backfill_prices, daily_prices
from dags.backfill_prices import plan_months
from dags.timetables import NYSECloseTimetable
from oap.ingest import dolthub_stocks
from oap.ingest.iceberg_writer import (
    catalog_from_env,
    content_hash,
    ensure_table,
    read_partition,
    write_partition,
)
from oap.ingest.price_schema import PRICE_SCHEMA
from oap.ingest.schema import empty_frame
from oap.ingest.tables import UNDERLYING_PRICE
from tests.ingest.price_factory import price_frame

DAG_FOLDER = Path(__file__).resolve().parents[2] / "dags"
SOURCE = "dolthub_stocks"
D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
JANUARY = {"month": "2024-01", "start": "2024-01-02", "end": "2024-01-31"}

Task = Callable[..., Any]


# DAG structure


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAG_FOLDER), include_examples=False)


def test_the_price_dags_import_cleanly(dagbag: DagBag) -> None:
    errors = {path: error for path, error in dagbag.import_errors.items() if "prices" in path}
    assert errors == {}
    assert {"backfill_prices", "daily_prices"} <= set(dagbag.dag_ids)


def test_task_ids(dagbag: DagBag) -> None:
    assert set(dagbag.dags["backfill_prices"].task_ids) == {
        "plan",
        "fetch_month",
        "write_month",
        "summarize",
    }
    assert set(dagbag.dags["daily_prices"].task_ids) == {"fetch", "write"}


def test_writers_share_the_single_slot_pool_and_fetches_do_not(dagbag: DagBag) -> None:
    backfill = dagbag.dags["backfill_prices"]
    daily = dagbag.dags["daily_prices"]

    assert backfill.get_task("write_month").pool == "bronze_writers"
    assert backfill.get_task("write_month").max_active_tis_per_dag == 1
    assert daily.get_task("write").pool == "bronze_writers"
    assert backfill.get_task("fetch_month").pool == "default_pool"
    assert daily.get_task("fetch").pool == "default_pool"


def test_backfill_runs_four_tasks_at_a_time_and_retries_fetches(dagbag: DagBag) -> None:
    dag = dagbag.dags["backfill_prices"]

    assert dag.max_active_tasks == 4
    assert dag.max_active_runs == 1
    assert dag.catchup is False
    assert dag.schedule_interval is None
    fetch = dag.get_task("fetch_month")
    assert fetch.retries == 5
    assert fetch.retry_exponential_backoff
    assert fetch.get_direct_relative_ids(upstream=False) == {"write_month"}


def test_backfill_end_param_is_required(dagbag: DagBag) -> None:
    params = dagbag.dags["backfill_prices"].params

    assert not params.get_param("end").has_value
    assert params["start"] == "2020-01-01"
    assert params["symbols"] == []


def test_daily_prices_uses_the_nyse_timetable_and_runs_in_order(dagbag: DagBag) -> None:
    dag = dagbag.dags["daily_prices"]

    assert isinstance(dag.timetable, NYSECloseTimetable)
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.get_task("fetch").downstream_task_ids == {"write"}


# plan_months


def test_plan_months() -> None:
    jobs = plan_months(date(2024, 3, 1), date(2024, 4, 30), ["spy", "QQQ", "SPY"])

    assert jobs == [
        {"month": "2024-03", "start": "2024-03-01", "end": "2024-03-28", "symbols": ["SPY", "QQQ"]},
        {"month": "2024-04", "start": "2024-04-01", "end": "2024-04-30", "symbols": ["SPY", "QQQ"]},
    ]


def test_plan_months_clips_to_sessions() -> None:
    # 2023-12-30/31 are a weekend and 2024-01-01 a holiday.
    jobs = plan_months(date(2023, 12, 30), date(2024, 1, 31), ["SPY"])

    assert [(job["month"], job["start"]) for job in jobs] == [("2024-01", "2024-01-02")]


def test_plan_months_of_empty_symbols_reads_the_watchlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backfill_prices, "read_watchlist", lambda: ["AAA", "BBB"])

    jobs = plan_months(date(2024, 1, 2), date(2024, 1, 31), [])

    assert jobs[0]["symbols"] == ["AAA", "BBB"]


def test_plan_months_of_a_range_without_sessions_is_empty() -> None:
    assert plan_months(date(2024, 1, 6), date(2024, 1, 7), ["SPY"]) == []


@pytest.mark.parametrize("symbols", [["SPY'"], ["TOOLONGSYMBOL"], [5]])
def test_plan_months_rejects_malformed_symbols(symbols: list[Any]) -> None:
    with pytest.raises(ValueError):
        plan_months(date(2024, 1, 2), date(2024, 1, 31), symbols)


def test_plan_months_rejects_a_reversed_range() -> None:
    with pytest.raises(ValueError):
        plan_months(date(2024, 2, 1), date(2024, 1, 1), ["SPY"])


# fetch_month and write_month


@pytest.fixture
def table(tmp_path: Path) -> Table:
    catalog = catalog_from_env(
        {
            "OAP_ICEBERG_CATALOG": "sql",
            "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/catalog.db",
            "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/warehouse",
        }
    )
    return ensure_table(catalog, spec=UNDERLYING_PRICE)


@pytest.fixture
def staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: Table) -> Path:
    """A test staging dir; the DAG module resolves the table and the run id from the test."""
    path = tmp_path / "staging"
    path.mkdir()
    monkeypatch.setattr(backfill_prices, "bronze_table", lambda spec=None: table)
    monkeypatch.setattr(backfill_prices, "staging_dir", lambda *parts: path)
    monkeypatch.setattr(backfill_prices, "get_current_context", lambda: {"run_id": "test"})
    return path


def _task(name: str) -> Task:
    task = backfill_prices.backfill_prices().get_task(name)
    return cast(Task, cast(Any, task).python_callable)


def _seed(table: Table) -> None:
    for day in (D1, D2):
        frame = price_frame(day, ("SPY", "QQQ"))
        write_partition(table, frame, trade_date=day, source=SOURCE)


def _spy(day: date, seed: int) -> pd.DataFrame:
    return price_frame(day, ("SPY",), seed)


def _by_underlying(table: Table, day: date) -> dict[str, int]:
    frame = read_partition(table, trade_date=day, source=SOURCE)
    return {str(k): int(v) for k, v in frame.groupby("underlying", observed=True).size().items()}


def test_a_staged_month_merges_and_keeps_other_underlyings(table: Table, staging: Path) -> None:
    _seed(table)
    qqq_before = read_partition(table, trade_date=D1, source=SOURCE)
    qqq_before = qqq_before[qqq_before["underlying"] == "QQQ"]
    fetched = pd.concat([_spy(D1, seed=1), _spy(D2, seed=1)], ignore_index=True)
    fetched.to_parquet(staging / "2024-01.parquet", index=False)

    result = _task("write_month")({**JANUARY, "symbols": ["SPY", "QQQ"]})

    assert result == {"month": "2024-01", "days": 2, "unchanged": 0, "rows": 4}
    after = read_partition(table, trade_date=D1, source=SOURCE)
    assert _by_underlying(table, D1) == {"QQQ": 1, "SPY": 1}
    assert content_hash(after[after["underlying"] == "QQQ"], spec=UNDERLYING_PRICE) == content_hash(
        qqq_before, spec=UNDERLYING_PRICE
    )
    assert not (staging / "2024-01.parquet").exists()


def test_rerunning_a_month_reports_every_day_unchanged(table: Table, staging: Path) -> None:
    fetched = pd.concat([_spy(D1, seed=1), _spy(D2, seed=1)], ignore_index=True)
    write_month = _task("write_month")
    fetched.to_parquet(staging / "2024-01.parquet", index=False)
    write_month({**JANUARY, "symbols": ["SPY"]})
    snapshots = len(table.refresh().metadata.snapshots)
    fetched.to_parquet(staging / "2024-01.parquet", index=False)

    result = write_month({**JANUARY, "symbols": ["SPY"]})

    assert result == {"month": "2024-01", "days": 0, "unchanged": 2, "rows": 0}
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_an_empty_month_writes_nothing(table: Table, staging: Path) -> None:
    _seed(table)
    snapshots = len(table.refresh().metadata.snapshots)
    (staging / "2024-01.empty").touch()

    result = _task("write_month")({**JANUARY, "symbols": ["SPY"]})

    assert result == {"month": "2024-01", "days": 0, "unchanged": 0, "rows": 0}
    assert _by_underlying(table, D1) == {"QQQ": 1, "SPY": 1}
    assert len(table.refresh().metadata.snapshots) == snapshots
    assert not (staging / "2024-01.empty").exists()


def test_a_month_whose_fetch_failed_fails_its_write(table: Table, staging: Path) -> None:
    _seed(table)

    with pytest.raises(AirflowFailException, match="2024-01: fetch failed"):
        _task("write_month")({**JANUARY, "symbols": ["SPY"]})
    assert _by_underlying(table, D1) == {"QQQ": 1, "SPY": 1}


def test_fetch_month_stages_a_parquet_that_write_month_reads(
    table: Table, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], date, date]] = []

    def fake_fetch(symbols: list[str], start: date, end: date, **_: Any) -> pd.DataFrame:
        calls.append((symbols, start, end))
        return pd.concat([_spy(D1, seed=2), _spy(D2, seed=2)], ignore_index=True)

    monkeypatch.setattr(dolthub_stocks, "fetch_prices", fake_fetch)

    staged = _task("fetch_month")({**JANUARY, "symbols": ["SPY"]})

    assert staged == {"month": "2024-01", "rows": 2, "days": 2}
    assert calls == [(["SPY"], date(2024, 1, 2), date(2024, 1, 31))]
    assert not list(staging.glob("*.partial"))
    result = _task("write_month")({**JANUARY, "symbols": ["SPY"]})
    assert result["rows"] == 2
    assert _by_underlying(table, D1) == {"SPY": 1}


def test_fetch_month_skips_a_month_without_rows(
    staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dolthub_stocks,
        "fetch_prices",
        lambda *a, **k: empty_frame(PRICE_SCHEMA),
    )

    with pytest.raises(AirflowSkipException):
        _task("fetch_month")({**JANUARY, "symbols": ["SPY"]})
    assert (staging / "2024-01.empty").exists()


def test_summarize_totals_the_months() -> None:
    results = [
        {"month": "2024-01", "days": 2, "unchanged": 1, "rows": 40},
        {"month": "2024-02", "days": 3, "unchanged": 0, "rows": 60},
    ]

    assert _task("summarize")(results) == {"months": 2, "days": 5, "unchanged": 1, "rows": 100}


# daily_prices


@pytest.fixture
def daily(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: Table) -> Callable[[str], Task]:
    monkeypatch.setattr(daily_prices, "bronze_table", lambda spec=None: table)
    monkeypatch.setattr(daily_prices, "staging_dir", lambda *parts: tmp_path)
    monkeypatch.setattr(daily_prices, "read_watchlist", lambda: ["SPY", "QQQ"])
    monkeypatch.setattr(
        daily_prices,
        "get_current_context",
        lambda: {"data_interval_end": datetime(2024, 1, 9, 21, 30, tzinfo=UTC)},
    )

    def get(name: str) -> Task:
        task = daily_prices.daily_prices().get_task(name)
        return cast(Task, cast(Any, task).python_callable)

    return get


def test_daily_fetch_asks_for_the_last_five_sessions(
    daily: Callable[[str], Task], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], date, date]] = []

    def fake_fetch(symbols: list[str], start: date, end: date, **_: Any) -> pd.DataFrame:
        calls.append((symbols, start, end))
        return _spy(D1, seed=4)

    monkeypatch.setattr(dolthub_stocks, "fetch_prices", fake_fetch)

    path = daily("fetch")()

    # 2024-01-09 is a Tuesday; the five sessions are Jan 3, 4, 5, 8 and 9.
    assert calls == [(["SPY", "QQQ"], date(2024, 1, 3), date(2024, 1, 9))]
    assert path == str(tmp_path / "2024-01-09.parquet")
    assert len(pd.read_parquet(path)) == 1


def test_daily_fetch_fails_on_an_empty_window(
    daily: Callable[[str], Task], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dolthub_stocks,
        "fetch_prices",
        lambda *a, **k: empty_frame(PRICE_SCHEMA),
    )

    with pytest.raises(AirflowFailException, match="no prices"):
        daily("fetch")()


def test_daily_write_merges_into_the_slices_and_is_idempotent(
    daily: Callable[[str], Task], table: Table, tmp_path: Path
) -> None:
    _seed(table)
    path = tmp_path / "window.parquet"
    pd.concat([_spy(D1, seed=1), _spy(D2, seed=1)], ignore_index=True).to_parquet(path, index=False)

    first = daily("write")(str(path))
    second = daily("write")(str(path))

    assert first == {"days": 2, "unchanged": 0, "rows": 4}
    assert second == {"days": 0, "unchanged": 2, "rows": 0}
    assert _by_underlying(table, D1) == {"QQQ": 1, "SPY": 1}
