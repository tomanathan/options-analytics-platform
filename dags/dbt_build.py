"""Build the silver and gold layers with dbt after bronze changes.

``dbt_build`` is scheduled on the ``BRONZE_OPTION_CHAIN`` and ``BRONZE_UNDERLYING_PRICE``
Datasets, so it runs whenever either bronze table has been updated; ``max_active_runs=1``
keeps one writer on the DuckDB file. It has one task, ``dbt_build``, which runs
``/opt/dbt-venv/bin/dbt`` (dbt lives in its own virtualenv, see ``docker/airflow.Dockerfile``)
against the ``dev`` target.

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

Only one process may write ``oap.duckdb`` at a time, so do not run ``make dbt-build-local``
while this DAG runs.
"""

import re
import shlex
from datetime import UTC, datetime, timedelta

from airflow.decorators import dag, task
from airflow.models.param import Param
from airflow.operators.python import get_current_context

from dags.common import DEFAULT_ARGS
from dags.datasets import BRONZE_OPTION_CHAIN, BRONZE_UNDERLYING_PRICE

DBT_BIN = "/opt/dbt-venv/bin/dbt"
AIRFLOW_HOME = "/opt/airflow"
ARTIFACTS_DIR = f"{AIRFLOW_HOME}/.dbt-local/artifacts"
MODES = ("build", "test")
DBT_ENV = {
    "DBT_PROFILES_DIR": f"{AIRFLOW_HOME}/dbt",
    "OAP_DBT_SOURCE": "iceberg",
    "OAP_ICEBERG_LOCAL_DIR": f"{AIRFLOW_HOME}/.iceberg-local",
    "OAP_DUCKDB_PATH": f"{AIRFLOW_HOME}/.dbt-local/oap.duckdb",
    "DBT_PACKAGES_INSTALL_PATH": "/opt/dbt-packages/dbt_packages",
    "OAP_DUCKDB_EXTENSION_DIR": "/opt/duckdb-extensions",
    "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
}
"""Environment of the dbt process: the container paths of the profile, catalog and image assets."""


def dbt_command(mode: str, *, full_refresh: bool, run_id: str) -> str:
    """Return the bash script that runs dbt once and publishes its artifacts.

    The project directory is mounted read-only, so dbt writes its target and logs to
    ``/tmp/dbt-target/<run_id>``, with the run id reduced to ``[A-Za-z0-9._-]``. An EXIT
    trap copies ``manifest.json`` and ``run_results.json`` to ``ARTIFACTS_DIR`` whether dbt
    succeeded or not, and keeps dbt's exit status.

    Args:
        mode: ``"build"`` (models and tests) or ``"test"`` (tests only).
        full_refresh: Pass ``--full-refresh`` so incremental models are rebuilt; ignored
            unless ``mode`` is ``"build"``.
        run_id: The Airflow run id, used to give each run its own target directory.

    Returns:
        The script text.

    Raises:
        ValueError: If ``mode`` is not one of ``MODES``.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    target = f"/tmp/dbt-target/{re.sub(r'[^A-Za-z0-9._-]', '_', run_id)}"
    args = [
        DBT_BIN,
        mode,
        "--project-dir",
        f"{AIRFLOW_HOME}/dbt",
        "--profiles-dir",
        f"{AIRFLOW_HOME}/dbt",
        "--target",
        "dev",
        "--target-path",
        target,
        "--log-path",
        target,
    ]
    if full_refresh and mode == "build":
        args.append("--full-refresh")
    publish = (
        f"mkdir -p {ARTIFACTS_DIR} && "
        f"cp {target}/manifest.json {target}/run_results.json {ARTIFACTS_DIR}/ 2>/dev/null || true"
    )
    return f"trap '{publish}' EXIT\n" + shlex.join(args)


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
        )

    dbt_build()


dbt_build()
