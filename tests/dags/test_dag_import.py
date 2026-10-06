from datetime import timedelta
from pathlib import Path

import pytest
from airflow.models import DagBag
from airflow.serialization.serialized_objects import SerializedDAG

from dags.timetables import NYSECloseTimetable

DAG_FOLDER = Path(__file__).resolve().parents[2] / "dags"

EXPECTED_TASKS = {
    "smoke": {"import_oap"},
    "backfill_chains": {"plan", "plan_months", "fetch_month", "write_month", "summarize"},
    "daily_chain_snapshot": {"snapshot", "write", "quality"},
    "iceberg_maintenance": {"expire_snapshots", "compact"},
}


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAG_FOLDER), include_examples=False)


def test_no_import_errors(dagbag: DagBag) -> None:
    assert dagbag.import_errors == {}


def test_exactly_the_expected_dags_are_loaded(dagbag: DagBag) -> None:
    assert set(dagbag.dag_ids) == set(EXPECTED_TASKS)


@pytest.mark.parametrize("dag_id", sorted(EXPECTED_TASKS))
def test_task_ids(dagbag: DagBag, dag_id: str) -> None:
    assert set(dagbag.dags[dag_id].task_ids) == EXPECTED_TASKS[dag_id]


def test_every_dag_retries_has_sla_and_logs_on_failure(dagbag: DagBag) -> None:
    assert dagbag.dags
    for dag_id, dag in dagbag.dags.items():
        default_args = dag.default_args
        assert default_args.get("retries", 0) >= 1, dag_id
        assert default_args.get("sla") == timedelta(hours=1), dag_id
        assert callable(default_args.get("on_failure_callback")), dag_id


def test_backfill_runs_four_tasks_at_a_time_and_writes_one_at_a_time(dagbag: DagBag) -> None:
    dag = dagbag.dags["backfill_chains"]
    assert dag.max_active_tasks == 4
    assert dag.max_active_runs == 1
    assert dag.get_task("write_month").max_active_tis_per_dag == 1
    fetch = dag.get_task("fetch_month")
    assert fetch.retries == 5
    assert fetch.retry_exponential_backoff
    assert fetch.max_retry_delay == timedelta(minutes=10)


def test_backfill_end_param_is_required(dagbag: DagBag) -> None:
    params = dagbag.dags["backfill_chains"].params
    assert not params.get_param("end").has_value
    assert params["start"] == "2020-01-01"
    assert params["symbols"] == []


def test_daily_snapshot_uses_the_nyse_timetable(dagbag: DagBag) -> None:
    dag = dagbag.dags["daily_chain_snapshot"]
    assert isinstance(dag.timetable, NYSECloseTimetable)
    assert dag.catchup is False
    assert dag.max_active_runs == 1


def test_daily_snapshot_tasks_run_in_order(dagbag: DagBag) -> None:
    dag = dagbag.dags["daily_chain_snapshot"]
    assert dag.get_task("snapshot").downstream_task_ids == {"write"}
    assert dag.get_task("write").downstream_task_ids == {"quality"}


def test_scheduler_can_rebuild_the_timetable_from_the_serialized_dag(dagbag: DagBag) -> None:
    # Fails with "Timetable class ... is not registered" unless the plugin registers the
    # class under the import path the DAG file uses.
    serialized = SerializedDAG.to_dict(dagbag.dags["daily_chain_snapshot"])
    restored = SerializedDAG.from_dict(serialized)
    assert isinstance(restored.timetable, NYSECloseTimetable)
    assert restored.timetable.summary == "NYSE close 16:30 ET"
