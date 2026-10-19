from pathlib import Path
from typing import Any

import yaml

from dags.common import BRONZE_WRITERS_POOL

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _init_service() -> dict[str, Any]:
    services: dict[str, dict[str, Any]] = yaml.safe_load(COMPOSE.read_text())["services"]
    return services["airflow-init"]


def test_airflow_init_creates_the_single_slot_bronze_pool() -> None:
    command = " ".join(_init_service()["command"])

    assert f"airflow pools set {BRONZE_WRITERS_POOL} 1" in command
    assert BRONZE_WRITERS_POOL == "bronze_writers"


def test_airflow_init_still_migrates_the_database() -> None:
    service = _init_service()

    assert "airflow version" in " ".join(service["command"])
    assert service["environment"]["_AIRFLOW_DB_MIGRATE"] == "true"
