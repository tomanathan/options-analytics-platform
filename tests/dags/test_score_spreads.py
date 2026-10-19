import shlex
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from airflow.datasets import Dataset
from airflow.models import DagBag

from dags import dbt_runner
from dags.datasets import GOLD, GOLD_ANALYTICS

DAG_FOLDER = Path(__file__).resolve().parents[2] / "dags"
COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAG_FOLDER), include_examples=False)


def test_analytics_runs_before_the_report(dagbag: DagBag) -> None:
    dag = dagbag.dags["score_spreads"]

    assert set(dag.task_ids) == {"analytics", "report"}
    assert dag.get_task("analytics").downstream_task_ids == {"report"}
    assert dag.get_task("report").downstream_task_ids == set()


def test_it_runs_when_the_gold_dataset_is_updated(dagbag: DagBag) -> None:
    condition: Any = dagbag.dags["score_spreads"].timetable.dataset_condition

    assert [cast(Dataset, d).uri for d in condition.objects] == [GOLD.uri]


def test_one_run_at_a_time(dagbag: DagBag) -> None:
    dag = dagbag.dags["score_spreads"]

    assert dag.max_active_runs == 1
    assert dag.catchup is False


def test_both_tasks_share_the_single_duckdb_writer_slot(dagbag: DagBag) -> None:
    dag = dagbag.dags["score_spreads"]

    assert dbt_runner.DUCKDB_POOL == "duckdb_writer"
    assert {dag.get_task(t).pool for t in dag.task_ids} == {"duckdb_writer"}


def test_the_analytics_task_updates_its_own_dataset(dagbag: DagBag) -> None:
    outlets = dagbag.dags["score_spreads"].get_task("analytics").outlets

    assert [cast(Dataset, o).uri for o in outlets] == [GOLD_ANALYTICS.uri]
    assert GOLD_ANALYTICS.uri != GOLD.uri
    assert not dagbag.dags["score_spreads"].get_task("report").outlets


def test_the_analytics_task_builds_only_the_analytics_selection(
    dagbag: DagBag, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = cast(Any, dagbag.dags["score_spreads"].get_task("analytics"))
    context = {"run_id": "manual__1"}
    # DagBag loads the file under its own module name, so patch the globals the task body sees.
    monkeypatch.setitem(task.python_callable.__globals__, "get_current_context", lambda: context)

    script = task.python_callable()

    assert "/opt/dbt-venv/bin/dbt build " in script
    assert script.endswith("--select tag:analytics")
    assert "--exclude" not in script
    assert "--full-refresh" not in script
    assert task.env["OAP_DBT_SOURCE"] == "iceberg"


def test_the_report_runs_in_the_dbt_virtualenv_into_the_report_directory(
    dagbag: DagBag,
) -> None:
    task = cast(Any, dagbag.dags["score_spreads"].get_task("report"))

    command = shlex.split(task.python_callable())

    assert command[0] == "/opt/dbt-venv/bin/python"
    assert command[1] == "/opt/airflow/scripts/make_report.py"
    assert command[command.index("--out") + 1] == dbt_runner.REPORT_DIR
    assert command[command.index("--db") + 1] == dbt_runner.DBT_ENV["OAP_DUCKDB_PATH"]
    assert dbt_runner.REPORT_DIR == "/opt/airflow/.dbt-local/report"
    assert task.env["MPLCONFIGDIR"]


def test_the_report_directory_is_inside_the_writable_state_mount() -> None:
    mounts = yaml.safe_load(COMPOSE.read_text())["x-airflow-common"]["volumes"]

    assert "./.dbt-local:/opt/airflow/.dbt-local" in mounts
    assert dbt_runner.REPORT_DIR.startswith("/opt/airflow/.dbt-local/")
    assert "./docs:/opt/airflow/docs" not in mounts


def test_airflow_init_creates_the_single_slot_duckdb_pool() -> None:
    command = " ".join(yaml.safe_load(COMPOSE.read_text())["services"]["airflow-init"]["command"])

    assert f"airflow pools set {dbt_runner.DUCKDB_POOL} 1" in command
