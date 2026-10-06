"""Airflow configuration for the DAG tests, set before anything imports airflow.

Airflow reads its config on first import, and test modules here import it at collection
time, so the environment is set at conftest import. Unit test mode parses DAGs without a
metadata database; the plugins folder is the repository's so the custom timetable is
registered the way the scheduler registers it.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

AIRFLOW_HOME = tempfile.mkdtemp(prefix="oap-airflow-home-")
atexit.register(shutil.rmtree, AIRFLOW_HOME, ignore_errors=True)

os.environ["AIRFLOW_HOME"] = AIRFLOW_HOME
os.environ["AIRFLOW__CORE__UNIT_TEST_MODE"] = "True"
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
os.environ["AIRFLOW__CORE__DAGS_FOLDER"] = str(REPO / "dags")
os.environ["AIRFLOW__CORE__PLUGINS_FOLDER"] = str(REPO / "plugins")
