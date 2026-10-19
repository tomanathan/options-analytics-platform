from pathlib import Path
from typing import Any, cast

import pytest
from airflow.datasets import Dataset, DatasetAny
from airflow.exceptions import AirflowSkipException
from airflow.models import DagBag

from dags import dbt_runner
from dags.datasets import BRONZE_OPTION_CHAIN, BRONZE_UNDERLYING_PRICE, GOLD

DAG_FOLDER = Path(__file__).resolve().parents[2] / "dags"


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAG_FOLDER), include_examples=False)


def test_dbt_build_runs_the_build_then_publishes_gold(dagbag: DagBag) -> None:
    dag = dagbag.dags["dbt_build"]

    assert set(dag.task_ids) == {"dbt_build", "publish_gold"}
    assert dag.get_task("dbt_build").downstream_task_ids == {"publish_gold"}
    assert dag.get_task("publish_gold").downstream_task_ids == set()


def test_it_runs_when_either_bronze_table_is_updated(dagbag: DagBag) -> None:
    schedule = dagbag.dags["dbt_build"].timetable.dataset_condition
    assert isinstance(schedule, DatasetAny)
    assert {cast(Dataset, d).uri for d in schedule.objects} == {
        "iceberg://oap/bronze/option_chain",
        "iceberg://oap/bronze/underlying_price",
    }
    assert BRONZE_OPTION_CHAIN.uri != BRONZE_UNDERLYING_PRICE.uri


def test_dbt_build_leaves_the_analytics_models_to_score_spreads(
    dagbag: DagBag, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = {"run_id": "r", "params": {"mode": "build", "full_refresh": False}}
    task = cast(Any, dagbag.dags["dbt_build"].get_task("dbt_build"))
    # DagBag loads the file under its own module name, so patch the globals the task body sees.
    monkeypatch.setitem(task.python_callable.__globals__, "get_current_context", lambda: context)

    script = task.python_callable()

    assert script.endswith("--exclude tag:analytics")
    assert "--select" not in script


def test_dbt_build_runs_in_the_duckdb_pool_and_publish_gold_owns_the_outlet(
    dagbag: DagBag,
) -> None:
    dag = dagbag.dags["dbt_build"]
    bash = dag.get_task("dbt_build")
    publish = dag.get_task("publish_gold")

    assert bash.pool == dbt_runner.DUCKDB_POOL == "duckdb_writer"
    assert not bash.outlets
    assert [cast(Dataset, o).uri for o in publish.outlets] == [GOLD.uri] == ["duckdb://oap/gold"]


def _publish_gold(dagbag: DagBag, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    context = {"run_id": "r", "params": {"mode": mode, "full_refresh": False}}
    task = cast(Any, dagbag.dags["dbt_build"].get_task("publish_gold"))
    monkeypatch.setitem(task.python_callable.__globals__, "get_current_context", lambda: context)
    task.python_callable()


def test_publish_gold_skips_after_a_test_run_so_no_dataset_event_fires(
    dagbag: DagBag, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(AirflowSkipException, match="mode=test"):
        _publish_gold(dagbag, monkeypatch, "test")


def test_publish_gold_succeeds_after_a_build_run(
    dagbag: DagBag, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish_gold(dagbag, monkeypatch, "build")


def test_select_and_exclude_are_rendered_as_dbt_flags() -> None:
    script = dbt_runner.dbt_command(
        "build",
        full_refresh=False,
        run_id="r",
        select=("tag:analytics", "fct_option_quote"),
        exclude=("tag:slow",),
    )

    assert "--select tag:analytics fct_option_quote" in script
    assert script.endswith("--exclude tag:slow")


def test_no_selection_flags_by_default() -> None:
    script = dbt_runner.dbt_command("build", full_refresh=False, run_id="r")

    assert "--select" not in script
    assert "--exclude" not in script


def test_one_run_at_a_time_with_build_and_no_full_refresh_by_default(dagbag: DagBag) -> None:
    dag = dagbag.dags["dbt_build"]
    assert dag.max_active_runs == 1
    assert dag.catchup is False
    assert dag.params["mode"] == "build"
    assert dag.params["full_refresh"] is False


@pytest.mark.parametrize(
    ("dag_id", "task_id"),
    [("daily_chain_snapshot", "write"), ("backfill_chains", "summarize")],
)
def test_chain_producers_update_the_option_chain_dataset(
    dagbag: DagBag, dag_id: str, task_id: str
) -> None:
    outlets = dagbag.dags[dag_id].get_task(task_id).outlets
    assert [cast(Dataset, o).uri for o in outlets] == [BRONZE_OPTION_CHAIN.uri]


def test_the_daily_gate_and_the_backfill_month_writes_do_not_update_the_dataset(
    dagbag: DagBag,
) -> None:
    # The daily dataset moves only after the gate passed and the slice landed (its write task);
    # the backfill's moves after the whole backfill has passed.
    assert not dagbag.dags["daily_chain_snapshot"].get_task("quality").outlets
    assert not dagbag.dags["backfill_chains"].get_task("write_month").outlets


def test_build_command_runs_dbt_build_on_the_dev_target() -> None:
    script = dbt_runner.dbt_command("build", full_refresh=False, run_id="scheduled__x")

    assert "/opt/dbt-venv/bin/dbt build " in script
    assert "--target dev" in script
    assert "--project-dir /opt/airflow/dbt" in script
    assert "--full-refresh" not in script


def test_test_command_runs_only_tests_and_never_refreshes() -> None:
    script = dbt_runner.dbt_command("test", full_refresh=True, run_id="manual__x")

    assert "/opt/dbt-venv/bin/dbt test " in script
    assert "--full-refresh" not in script


def test_full_refresh_is_passed_to_build() -> None:
    assert "--full-refresh" in dbt_runner.dbt_command("build", full_refresh=True, run_id="r")


def test_target_path_is_the_sanitized_run_id() -> None:
    run_id = "manual__2026-10-05T22:00:00+00:00"
    script = dbt_runner.dbt_command("build", full_refresh=False, run_id=run_id)

    target = "/tmp/dbt-target/manual__2026-10-05T22_00_00_00_00"
    assert f"--target-path {target}" in script
    assert f"--log-path {target}" in script


def test_artifacts_are_copied_by_an_exit_trap_so_failures_publish_them() -> None:
    script = dbt_runner.dbt_command("build", full_refresh=False, run_id="r1")
    trap, command = script.split("\n", 1)

    assert trap.startswith("trap ") and trap.endswith(" EXIT")
    assert "/tmp/dbt-target/r1/manifest.json" in trap
    assert "/tmp/dbt-target/r1/run_results.json" in trap
    assert f"{dbt_runner.ARTIFACTS_DIR}/" in trap
    assert command.startswith(dbt_runner.DBT_BIN)


def test_an_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="mode"):
        dbt_runner.dbt_command("run", full_refresh=False, run_id="r")


def test_dbt_reads_the_real_catalog_in_the_container() -> None:
    assert dbt_runner.DBT_ENV["OAP_DBT_SOURCE"] == "iceberg"
    assert dbt_runner.DBT_ENV["OAP_ICEBERG_LOCAL_DIR"] == "/opt/airflow/.iceberg-local"
