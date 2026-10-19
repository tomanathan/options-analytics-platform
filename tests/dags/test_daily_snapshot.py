from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from airflow.datasets import Dataset
from airflow.exceptions import AirflowFailException
from pyiceberg.table import Table

from dags import daily_chain_snapshot
from dags.datasets import BRONZE_OPTION_CHAIN
from oap.calendar import trading_days
from oap.ingest import iceberg_writer
from oap.ingest.iceberg_writer import (
    catalog_from_env,
    ensure_table,
    read_partition,
    write_partition,
)
from oap.ingest.schema import empty_frame
from tests.bronze_factory import bronze_frame

SESSION = date(2024, 1, 17)
SOURCE = "alpaca_indicative"
USUAL_ROWS = 40

Task = Callable[..., Any]


def test_snapshot_without_credentials_fails_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr(daily_chain_snapshot, "_session", lambda: date(2026, 10, 16))
    task = daily_chain_snapshot.daily_chain_snapshot().get_task("snapshot")

    with pytest.raises(AirflowFailException, match="ALPACA_API_KEY"):
        cast(Any, task).python_callable()


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
def tasks(table: Table, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Task]:
    """The DAG's task callables, bound to a temporary table and the session ``SESSION``."""
    monkeypatch.setattr(daily_chain_snapshot, "bronze_table", lambda spec=None: table)
    monkeypatch.setattr(daily_chain_snapshot, "_session", lambda: SESSION)

    def get(name: str) -> Task:
        task = daily_chain_snapshot.daily_chain_snapshot().get_task(name)
        return cast(Task, cast(Any, task).python_callable)

    return get


def _seed_history(table: Table) -> None:
    """Write six prior sessions of the source at ``USUAL_ROWS`` rows each (SPY only)."""
    for day in trading_days(date(2024, 1, 8), date(2024, 1, 16)):
        frame = bronze_frame(day, rows_per_underlying=USUAL_ROWS, source=SOURCE, seed=day.day)
        write_partition(table, frame, trade_date=day, source=SOURCE)


def _stage(tmp_path: Path, rows: int) -> str:
    path = tmp_path / f"{SESSION.isoformat()}.parquet"
    bronze_frame(SESSION, rows_per_underlying=rows, source=SOURCE).to_parquet(path, index=False)
    return str(path)


def _slice_rows(table: Table) -> int:
    return len(read_partition(table, trade_date=SESSION, source=SOURCE))


def test_tasks_run_snapshot_then_quality_then_write() -> None:
    dag = daily_chain_snapshot.daily_chain_snapshot()

    assert dag.get_task("snapshot").downstream_task_ids == {"quality"}
    assert dag.get_task("quality").downstream_task_ids == {"write"}
    assert dag.get_task("write").downstream_task_ids == set()


def test_only_write_updates_the_option_chain_dataset() -> None:
    dag = daily_chain_snapshot.daily_chain_snapshot()

    outlets = dag.get_task("write").outlets
    assert [cast(Dataset, o).uri for o in outlets] == [BRONZE_OPTION_CHAIN.uri]
    assert not dag.get_task("snapshot").outlets
    assert not dag.get_task("quality").outlets


def test_quality_passes_a_normal_staged_slice_and_hands_on_its_path(
    tasks: Callable[[str], Task], table: Table, tmp_path: Path
) -> None:
    _seed_history(table)
    staged = _stage(tmp_path, USUAL_ROWS)

    assert tasks("quality")(staged) == staged
    assert _slice_rows(table) == 0


def test_a_gate_failed_slice_is_never_written(
    tasks: Callable[[str], Task], table: Table, tmp_path: Path
) -> None:
    _seed_history(table)
    staged = _stage(tmp_path, 5)
    snapshots = len(table.refresh().metadata.snapshots)

    with pytest.raises(AirflowFailException, match="row_count:SPY"):
        tasks("quality")(staged)

    assert _slice_rows(table) == 0
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_a_gate_failure_leaves_the_previous_slice_of_the_session_in_place(
    tasks: Callable[[str], Task], table: Table, tmp_path: Path
) -> None:
    _seed_history(table)
    previous = bronze_frame(SESSION, rows_per_underlying=USUAL_ROWS, source=SOURCE)
    write_partition(table, previous, trade_date=SESSION, source=SOURCE)

    with pytest.raises(AirflowFailException):
        tasks("quality")(_stage(tmp_path, 5))

    assert _slice_rows(table) == USUAL_ROWS


def test_write_commits_the_staged_slice_and_returns_its_row_count(
    tasks: Callable[[str], Task], table: Table, tmp_path: Path
) -> None:
    assert tasks("write")(_stage(tmp_path, USUAL_ROWS)) == USUAL_ROWS
    assert _slice_rows(table) == USUAL_ROWS


def test_write_fails_when_the_slice_read_back_has_another_row_count(
    tasks: Callable[[str], Task], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(iceberg_writer, "read_partition", lambda *a, **k: empty_frame())

    with pytest.raises(AirflowFailException, match="wrote 40 rows but the slice holds 0"):
        tasks("write")(_stage(tmp_path, USUAL_ROWS))
