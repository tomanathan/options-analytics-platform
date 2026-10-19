import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from oap.ingest.price_schema import PRICE_SCHEMA
from oap.ingest.schema import BRONZE_SCHEMA

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


LAYER_SCHEMAS = {"staging": "silver", "intermediate": "silver", "marts": "gold"}


def _docs_blocks() -> set[str]:
    text = "\n".join(p.read_text() for p in (DBT_DIR / "models").rglob("*.md"))
    return set(re.findall(r"{%\s*docs\s+(\w+)\s*%}", text))


def _sources() -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = {}
    for path in sorted((DBT_DIR / "models").rglob("sources.yml")):
        for source in _load(path).get("sources", []):
            for table in source.get("tables", []):
                tables[f"{source['name']}.{table['name']}"] = table
    return tables


def test_every_model_sql_sits_in_a_layer_directory() -> None:
    models_dir = DBT_DIR / "models"
    for path in models_dir.rglob("*.sql"):
        assert path.relative_to(models_dir).parts[0] in LAYER_SCHEMAS, path


def test_layers_map_to_silver_and_gold() -> None:
    layers = _load(DBT_DIR / "dbt_project.yml")["models"]["oap"]
    assert {name: layers[name]["+schema"] for name in LAYER_SCHEMAS} == LAYER_SCHEMAS
    assert layers["marts"]["+materialized"] == "table"


@pytest.mark.parametrize("model", [m for _, m in MODELS], ids=lambda m: m["name"])
def test_model_description_is_its_docs_block(model: dict[str, Any]) -> None:
    assert model["description"] == "{{ doc('" + model["name"] + "') }}"
    assert model["name"] in _docs_blocks()


def test_option_chain_source_matches_the_bronze_schema() -> None:
    table = _sources()["bronze.option_chain"]
    assert [c["name"] for c in table["columns"]] == BRONZE_SCHEMA.names


def test_underlying_price_source_matches_the_price_schema() -> None:
    table = _sources()["bronze.underlying_price"]
    assert [c["name"] for c in table["columns"]] == PRICE_SCHEMA.names


@pytest.mark.parametrize("name", sorted(_sources()))
def test_source_and_its_columns_are_described(name: str) -> None:
    table = _sources()[name]
    assert str(table.get("description", "")).strip()
    for column in table["columns"]:
        assert str(column.get("description", "")).strip(), f"{name}.{column['name']}"


def test_incremental_models_replace_by_key_and_fail_on_schema_change() -> None:
    incremental = [
        p
        for p in (DBT_DIR / "models").rglob("*.sql")
        if "materialized='incremental'" in p.read_text()
    ]
    assert incremental
    for path in incremental:
        sql = path.read_text()
        assert "on_schema_change='fail'" in sql, path
        assert "unique_key" in sql, path


def test_bronze_is_registered_before_every_invocation() -> None:
    hooks = _load(DBT_DIR / "dbt_project.yml")["on-run-start"]
    assert any("register_bronze()" in hook for hook in hooks)


def test_synthetic_row_counts_test_runs_only_on_the_synthetic_catalog() -> None:
    sql = (DBT_DIR / "tests" / "assert_synthetic_row_counts.sql").read_text()
    assert "config(enabled=env_var('OAP_DBT_SOURCE', 'auto') == 'synthetic')" in sql
