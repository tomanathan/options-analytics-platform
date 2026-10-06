from pathlib import Path
from typing import Any

import pytest
import yaml

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"
MIN_TESTS_PER_MODEL = 2


def _load(path: Path) -> dict[str, Any]:
    with path.open() as f:
        loaded = yaml.safe_load(f)
    assert isinstance(loaded, dict), path
    return loaded


def _models() -> list[tuple[Path, dict[str, Any]]]:
    return [
        (path, model)
        for path in sorted((DBT_DIR / "models").rglob("schema.yml"))
        for model in _load(path).get("models", [])
    ]


def _test_count(entry: dict[str, Any]) -> int:
    tests = entry.get("data_tests", []) + entry.get("tests", [])
    return len(tests)


MODELS = _models()


def test_dbt_project_is_oap() -> None:
    project = _load(DBT_DIR / "dbt_project.yml")
    assert project["name"] == "oap"
    assert project["profile"] == "oap"


def test_every_model_sql_is_documented() -> None:
    sql_models = {p.stem for p in (DBT_DIR / "models").rglob("*.sql")}
    documented = {model["name"] for _, model in MODELS}
    assert sql_models
    assert sql_models <= documented


@pytest.mark.parametrize("model", [m for _, m in MODELS], ids=lambda m: m["name"])
def test_model_has_description(model: dict[str, Any]) -> None:
    assert str(model.get("description", "")).strip()


@pytest.mark.parametrize("model", [m for _, m in MODELS], ids=lambda m: m["name"])
def test_every_column_has_description(model: dict[str, Any]) -> None:
    columns = model.get("columns", [])
    assert columns, model["name"]
    for column in columns:
        assert str(column.get("description", "")).strip(), f"{model['name']}.{column['name']}"


@pytest.mark.parametrize("model", [m for _, m in MODELS], ids=lambda m: m["name"])
def test_model_has_at_least_two_tests(model: dict[str, Any]) -> None:
    total = _test_count(model) + sum(_test_count(c) for c in model.get("columns", []))
    assert total >= MIN_TESTS_PER_MODEL, model["name"]
