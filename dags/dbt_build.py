"""Build the silver and gold layers with dbt after bronze changes.

``dbt_build`` is scheduled on the ``BRONZE_OPTION_CHAIN`` and ``BRONZE_UNDERLYING_PRICE``
Datasets, so it runs whenever either bronze table has been updated; ``max_active_runs=1``
keeps one writer on the DuckDB file. Tasks run ``dbt_build >> publish_gold``. ``dbt_build``
runs ``/opt/dbt-venv/bin/dbt`` (dbt lives in its own virtualenv, see
``docker/airflow.Dockerfile``) against the ``dev`` target.

* ``dbt build`` runs models and tests in dependency order. A dbt test failing at error
  severity skips every model downstream of it and fails the task: the dbt tests are the
  silver to gold gate (the Great Expectations suite remains the bronze gate).
* The task reads the Iceberg snapshot that the ``register_bronze`` hook pinned at the start of
  the run, so the models and their tests see the same bronze data even if a writer commits
  meanwhile.
* ``manifest.json`` and ``run_results.json`` are copied to ``.dbt-local/artifacts`` even when
  dbt fails.
* Params: ``mode`` is ``build`` (default) or ``test``, which runs only the tests against the
  existing tables. ``full_refresh`` (default false) rebuilds the incremental ``fct_option_quote``
  from scratch, which repairs drift that the watermark cannot see, such as a deleted bronze
  slice; it only applies to ``mode=build``.

* The Python models tagged ``analytics`` (calibration and spread scores) are excluded here and
  built by ``score_spreads``, which runs when this DAG succeeds: ``publish_gold`` updates the
  ``GOLD`` Dataset, so a failing silver or gold test blocks the analytics. ``publish_gold``
  raises ``AirflowSkipException`` unless ``params.mode`` is ``build``; a skipped task emits no
  Dataset event, so a ``mode=test`` run, which builds nothing, does not trigger the analytics.

Only one process may write ``oap.duckdb`` at a time. The task runs in the one-slot
``duckdb_writer`` pool, shared with ``score_spreads``; do not run ``make dbt-build-local`` or
``make report`` while either DAG runs.
"""

from datetime import UTC, datetime, timedelta

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException
from airflow.models.param import Param
from airflow.operators.python import get_current_context

from dags.common import DEFAULT_ARGS
from dags.datasets import BRONZE_OPTION_CHAIN, BRONZE_UNDERLYING_PRICE, GOLD
from dags.dbt_runner import AIRFLOW_HOME, DBT_ENV, DUCKDB_POOL, MODES, dbt_command


@dag(
    dag_id="dbt_build",
    schedule=BRONZE_OPTION_CHAIN | BRONZE_UNDERLYING_PRICE,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["phase-2", "silver", "gold"],
    params={"mode": Param("build", enum=list(MODES)), "full_refresh": Param(False, type="boolean")},
)
def dbt_build() -> None:
    """Run ``dbt build`` (or ``dbt test``) over the pinned bronze snapshot."""

    @task.bash(
        env=DBT_ENV,
        append_env=True,
        cwd=AIRFLOW_HOME,
        pool=DUCKDB_POOL,
        retries=1,
        retry_delay=timedelta(minutes=2),
    )
    def dbt_build() -> str:
        """Return the dbt script for this run's params."""
        context = get_current_context()
        return dbt_command(
            context["params"]["mode"],
            full_refresh=context["params"]["full_refresh"],
            run_id=context["run_id"],
            exclude=("tag:analytics",),
        )

    @task(outlets=[GOLD])
    def publish_gold() -> None:
        """Update the GOLD Dataset after a ``build`` run; skip after a ``test`` run.

        Raises:
            AirflowSkipException: If ``params.mode`` is not ``build``: nothing was built, so
                there is no new gold to announce.
        """
        mode = get_current_context()["params"]["mode"]
        if mode != "build":
            raise AirflowSkipException(f"mode={mode} builds nothing; GOLD not updated")

    dbt_build() >> publish_gold()


dbt_build()
