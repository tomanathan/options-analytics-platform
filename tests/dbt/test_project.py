import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from oap.analytics.backtest import (
    BIN_COLUMNS,
    MAP_COLUMNS,
    METRIC_COLUMNS,
    SAMPLE_COLUMNS,
)
from oap.analytics.io import OUTPUT_SCHEMAS
from oap.analytics.sample import PREDICTION_COLUMNS, SNAPSHOT_COLUMNS
from oap.analytics.scoring import SPREAD_COLUMNS
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


def _model_files() -> list[Path]:
    models_dir = DBT_DIR / "models"
    return sorted([*models_dir.rglob("*.sql"), *models_dir.rglob("*.py")])


def test_every_model_is_documented() -> None:
    names = {p.stem for p in _model_files()}
    documented = {model["name"] for _, model in MODELS}
    assert {p.stem for p in _model_files() if p.suffix == ".py"}, "the Python models are counted"
    assert names
    assert names <= documented
    assert documented <= names


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


LAYER_SCHEMAS = {
    "staging": "silver",
    "intermediate": "silver",
    "marts": "gold",
    "analytics": "gold",
}


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


def test_every_model_sits_in_a_layer_directory() -> None:
    models_dir = DBT_DIR / "models"
    for path in _model_files():
        assert path.relative_to(models_dir).parts[0] in LAYER_SCHEMAS, path


def test_python_models_live_only_in_the_analytics_layer() -> None:
    models_dir = DBT_DIR / "models"
    python_models = [p for p in _model_files() if p.suffix == ".py"]
    assert len(python_models) == 7
    assert {p.relative_to(models_dir).parts[0] for p in python_models} == {"analytics"}


def test_layers_map_to_silver_and_gold() -> None:
    layers = _load(DBT_DIR / "dbt_project.yml")["models"]["oap"]
    assert {name: layers[name]["+schema"] for name in LAYER_SCHEMAS} == LAYER_SCHEMAS
    assert layers["marts"]["+materialized"] == "table"


def test_analytics_is_a_gold_table_layer_tagged_and_disabled_off_duckdb() -> None:
    analytics = _load(DBT_DIR / "dbt_project.yml")["models"]["oap"]["analytics"]
    assert analytics["+schema"] == "gold"
    assert analytics["+materialized"] == "table"
    assert "analytics" in analytics["+tags"]
    assert "duckdb" in analytics["+enabled"]


def test_every_python_model_is_a_thin_wrapper_over_oap_analytics() -> None:
    for path in (DBT_DIR / "models" / "analytics").glob("*.py"):
        source = path.read_text()
        assert "def model(dbt" in source, path
        assert 'dbt.config(materialized="table")' in source, path
        assert "from oap.analytics" in source, path
        assert len(source.splitlines()) <= 30, path


def _described_columns(model: str) -> list[str]:
    entry = next(m for _, m in MODELS if m["name"] == model)
    return [c["name"] for c in entry["columns"]]


@pytest.mark.parametrize(
    ("model", "columns"),
    [
        ("calibration_snapshot", SNAPSHOT_COLUMNS),
        ("calibration_prediction", PREDICTION_COLUMNS),
        ("calibration_map", MAP_COLUMNS),
        ("calibration_sample", SAMPLE_COLUMNS),
        ("calibration_metrics", METRIC_COLUMNS),
        ("calibration_bins", BIN_COLUMNS),
        ("spread_scores", SPREAD_COLUMNS),
    ],
)
def test_schema_yml_describes_exactly_the_columns_the_model_writes(
    model: str, columns: tuple[str, ...]
) -> None:
    assert sorted(_described_columns(model)) == sorted(columns)
    assert tuple(OUTPUT_SCHEMAS[model]) == columns


ANALYTICS_SINGULAR_TESTS = [
    "assert_calibration_out_of_sample",
    "assert_calibration_map_monotone",
    "assert_predictions_from_ok_snapshots",
    "assert_spread_rank_contiguous",
    "assert_synthetic_analytics_counts",
]


@pytest.mark.parametrize("name", ANALYTICS_SINGULAR_TESTS)
def test_analytics_singular_tests_are_tagged_and_disabled_off_duckdb(name: str) -> None:
    sql = (DBT_DIR / "tests" / f"{name}.sql").read_text()
    config = sql.split("{{ config(", 1)[1].split(") }}", 1)[0]
    assert "tags=['analytics']" in config
    assert "target.type == 'duckdb'" in config


def test_synthetic_analytics_counts_test_runs_only_on_the_synthetic_catalog() -> None:
    sql = (DBT_DIR / "tests" / "assert_synthetic_analytics_counts.sql").read_text()
    assert "env_var('OAP_DBT_SOURCE', 'auto') == 'synthetic'" in sql


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
