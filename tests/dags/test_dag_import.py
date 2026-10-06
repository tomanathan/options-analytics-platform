from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from airflow.models import DagBag

DAG_FOLDER = Path(__file__).resolve().parents[2] / "dags"


@pytest.fixture(scope="module")
def dagbag(tmp_path_factory: pytest.TempPathFactory) -> Iterator["DagBag"]:
    # Airflow reads its config on first import, so the environment must be set before it.
    # Unit test mode parses DAGs without a metadata database.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("AIRFLOW_HOME", str(tmp_path_factory.mktemp("airflow_home")))
        mp.setenv("AIRFLOW__CORE__UNIT_TEST_MODE", "True")
        mp.setenv("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
        from airflow.models import DagBag

        yield DagBag(dag_folder=str(DAG_FOLDER), include_examples=False)


def test_no_import_errors(dagbag: "DagBag") -> None:
    assert dagbag.import_errors == {}


def test_smoke_dag_is_loaded(dagbag: "DagBag") -> None:
    assert "smoke" in dagbag.dag_ids


def test_every_dag_retries_has_sla_and_logs_on_failure(dagbag: "DagBag") -> None:
    assert dagbag.dags
    for dag_id, dag in dagbag.dags.items():
        default_args = dag.default_args
        assert default_args.get("retries", 0) >= 1, dag_id
        assert default_args.get("sla") == timedelta(hours=1), dag_id
        assert callable(default_args.get("on_failure_callback")), dag_id
