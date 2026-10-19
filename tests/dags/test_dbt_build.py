from pathlib import Path
from typing import cast

import pytest
from airflow.datasets import Dataset, DatasetAny
from airflow.models import DagBag

from dags import dbt_build
from dags.datasets import BRONZE_OPTION_CHAIN, BRONZE_UNDERLYING_PRICE

DAG_FOLDER = Path(__file__).resolve().parents[2] / "dags"


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAG_FOLDER), include_examples=False)


def test_dbt_build_has_one_task(dagbag: DagBag) -> None:
    assert set(dagbag.dags["dbt_build"].task_ids) == {"dbt_build"}


def test_it_runs_when_either_bronze_table_is_updated(dagbag: DagBag) -> None:
    schedule = dagbag.dags["dbt_build"].timetable.dataset_condition
    assert isinstance(schedule, DatasetAny)
    assert {cast(Dataset, d).uri for d in schedule.objects} == {
        "iceberg://oap/bronze/option_chain",
        "iceberg://oap/bronze/underlying_price",
    }
    assert BRONZE_OPTION_CHAIN.uri != BRONZE_UNDERLYING_PRICE.uri


def test_one_run_at_a_time_with_build_and_no_full_refresh_by_default(dagbag: DagBag) -> None:
    dag = dagbag.dags["dbt_build"]
    assert dag.max_active_runs == 1
    assert dag.catchup is False
    assert dag.params["mode"] == "build"
    assert dag.params["full_refresh"] is False


@pytest.mark.parametrize(
    ("dag_id", "task_id"),
    [("daily_chain_snapshot", "quality"), ("backfill_chains", "summarize")],
)
def test_chain_producers_update_the_option_chain_dataset(
    dagbag: DagBag, dag_id: str, task_id: str
) -> None:
    outlets = dagbag.dags[dag_id].get_task(task_id).outlets
    assert [cast(Dataset, o).uri for o in outlets] == [BRONZE_OPTION_CHAIN.uri]


def test_the_write_tasks_do_not_update_the_dataset(dagbag: DagBag) -> None:
    # The dataset must only move after the quality gate (or the whole backfill) has passed.
    assert not dagbag.dags["daily_chain_snapshot"].get_task("write").outlets
    assert not dagbag.dags["backfill_chains"].get_task("write_month").outlets


def test_build_command_runs_dbt_build_on_the_dev_target() -> None:
    script = dbt_build.dbt_command("build", full_refresh=False, run_id="scheduled__x")

    assert "/opt/dbt-venv/bin/dbt build " in script
    assert "--target dev" in script
    assert "--project-dir /opt/airflow/dbt" in script
    assert "--full-refresh" not in script


def test_test_command_runs_only_tests_and_never_refreshes() -> None:
    script = dbt_build.dbt_command("test", full_refresh=True, run_id="manual__x")

    assert "/opt/dbt-venv/bin/dbt test " in script
    assert "--full-refresh" not in script


def test_full_refresh_is_passed_to_build() -> None:
    assert "--full-refresh" in dbt_build.dbt_command("build", full_refresh=True, run_id="r")


def test_target_path_is_the_sanitized_run_id() -> None:
    run_id = "manual__2026-10-05T22:00:00+00:00"
    script = dbt_build.dbt_command("build", full_refresh=False, run_id=run_id)

    target = "/tmp/dbt-target/manual__2026-10-05T22_00_00_00_00"
    assert f"--target-path {target}" in script
    assert f"--log-path {target}" in script


def test_artifacts_are_copied_by_an_exit_trap_so_failures_publish_them() -> None:
    script = dbt_build.dbt_command("build", full_refresh=False, run_id="r1")
    trap, command = script.split("\n", 1)

    assert trap.startswith("trap ") and trap.endswith(" EXIT")
    assert "/tmp/dbt-target/r1/manifest.json" in trap
    assert "/tmp/dbt-target/r1/run_results.json" in trap
    assert f"{dbt_build.ARTIFACTS_DIR}/" in trap
    assert command.startswith(dbt_build.DBT_BIN)


def test_an_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="mode"):
        dbt_build.dbt_command("run", full_refresh=False, run_id="r")


def test_dbt_reads_the_real_catalog_in_the_container() -> None:
    assert dbt_build.DBT_ENV["OAP_DBT_SOURCE"] == "iceberg"
    assert dbt_build.DBT_ENV["OAP_ICEBERG_LOCAL_DIR"] == "/opt/airflow/.iceberg-local"
