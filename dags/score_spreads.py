"""Calibrate the risk-neutral distribution, score the latest put credit spreads, write the report.

The Dataset chain is bronze, then ``dbt_build``, then ``GOLD``, then this DAG: it is scheduled
on the ``GOLD`` Dataset, which ``dbt_build`` updates only when its models and tests have passed.
``max_active_runs=1`` keeps one run at a time. It has two tasks, in order:

* ``analytics`` runs ``dbt build --select tag:analytics``: the seven Python models over
  ``oap.analytics`` (snapshots, predictions, walk-forward calibration maps, the backtest
  sample, its metrics and reliability bins, and the spread scores) and their tests. A failing
  analytics test, among them the leakage gate ``assert_calibration_out_of_sample``, fails the
  task and blocks the report.
* ``report`` runs ``scripts/make_report.py`` with the dbt virtualenv, which writes
  ``results.md`` and the figures to ``.dbt-local/report/``. The committed copy under ``docs/``
  comes from ``make report`` on the host; both run the same code.

Both tasks open ``oap.duckdb``, so both run in the one-slot ``duckdb_writer`` pool that
``dbt_build`` shares; do not run ``make dbt-build-local`` or ``make report`` while this DAG runs.
"""

from datetime import UTC, datetime

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

from dags.common import DEFAULT_ARGS
from dags.datasets import GOLD, GOLD_ANALYTICS
from dags.dbt_runner import AIRFLOW_HOME, DBT_ENV, DUCKDB_POOL, dbt_command, report_command


@dag(
    dag_id="score_spreads",
    schedule=[GOLD],
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["phase-3", "analytics"],
)
def score_spreads() -> None:
    """Build the analytics models over the gold marts, then render the results report."""

    @task.bash(
        env=DBT_ENV,
        append_env=True,
        cwd=AIRFLOW_HOME,
        pool=DUCKDB_POOL,
        outlets=[GOLD_ANALYTICS],
    )
    def analytics() -> str:
        """Return the script that builds the analytics models and runs their tests."""
        context = get_current_context()
        return dbt_command(
            "build", full_refresh=False, run_id=context["run_id"], select=("tag:analytics",)
        )

    @task.bash(
        env={"MPLCONFIGDIR": "/tmp/matplotlib"},
        append_env=True,
        cwd=AIRFLOW_HOME,
        pool=DUCKDB_POOL,
    )
    def report() -> str:
        """Return the command that renders the report from the DuckDB file."""
        return report_command()

    analytics() >> report()


score_spreads()
