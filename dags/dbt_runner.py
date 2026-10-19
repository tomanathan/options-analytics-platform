"""Shell commands and constants for the DAGs that run dbt or the results report.

``dbt_build`` and ``score_spreads`` both run dbt inside the Airflow container, so the command
builder lives here instead of in either DAG file: a DAG file must not import another DAG
module (Airflow would register the imported DAG while parsing the importer). Like
``dags/datasets.py`` this module defines no DAG.

Only one process may write ``oap.duckdb`` at a time. Every task that opens the file (the dbt
build, the analytics build and the report) runs in the one-slot ``DUCKDB_POOL``.
"""

import re
import shlex
from collections.abc import Sequence

DBT_BIN = "/opt/dbt-venv/bin/dbt"
DBT_PYTHON = "/opt/dbt-venv/bin/python"
"""The dbt virtualenv's interpreter. It also holds ``oap.analytics`` and matplotlib."""
AIRFLOW_HOME = "/opt/airflow"
ARTIFACTS_DIR = f"{AIRFLOW_HOME}/.dbt-local/artifacts"
REPORT_DIR = f"{AIRFLOW_HOME}/.dbt-local/report"
"""Where the DAG writes ``results.md`` and ``img/*.png``; ``make report`` writes ``docs/``."""
DUCKDB_POOL = "duckdb_writer"
"""A one-slot Airflow pool created by ``airflow-init``; tasks that open ``oap.duckdb`` run in it."""
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


def dbt_command(
    mode: str,
    *,
    full_refresh: bool,
    run_id: str,
    select: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> str:
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
        select: dbt selectors passed as ``--select a b``, for example ``("tag:analytics",)``.
        exclude: dbt selectors passed as ``--exclude a b``.

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
    if select:
        args += ["--select", *select]
    if exclude:
        args += ["--exclude", *exclude]
    publish = (
        f"mkdir -p {ARTIFACTS_DIR} && "
        f"cp {target}/manifest.json {target}/run_results.json {ARTIFACTS_DIR}/ 2>/dev/null || true"
    )
    return f"trap '{publish}' EXIT\n" + shlex.join(args)


def report_command() -> str:
    """Return the command that writes the results report from the DuckDB file to ``REPORT_DIR``.

    It runs ``scripts/make_report.py`` with the dbt virtualenv's interpreter, which has
    ``oap.analytics`` and matplotlib. The script opens the database read-only.

    Returns:
        The command line, shell-quoted.
    """
    return shlex.join(
        [
            DBT_PYTHON,
            f"{AIRFLOW_HOME}/scripts/make_report.py",
            "--db",
            DBT_ENV["OAP_DUCKDB_PATH"],
            "--out",
            REPORT_DIR,
        ]
    )
