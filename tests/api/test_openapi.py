from pathlib import Path

from oap.api.main import create_app, openapi_text
from oap.api.settings import ApiSettings

COMMITTED = Path(__file__).resolve().parents[2] / "apps" / "web" / "openapi.json"

OPERATION_IDS = {
    "/healthz": "healthz",
    "/api/underlyings": "listUnderlyings",
    "/api/underlyings/{symbol}/sessions": "listSessions",
    "/api/underlyings/{symbol}/sessions/{session}/chain": "getChain",
    "/api/underlyings/{symbol}/sessions/{session}/distribution": "getDistribution",
    "/api/underlyings/{symbol}/sessions/{session}/heatmap": "getHeatmap",
    "/api/spreads": "listSpreads",
    "/api/spreads/{spread_key}": "getSpread",
    "/api/calibration/summary": "getCalibrationSummary",
    "/api/structures/map": "getOutcomeMap",
    "/api/structures/{symbol}/{session}": "getStructures",
}


def test_committed_openapi_matches_the_app() -> None:
    generated = openapi_text(create_app(ApiSettings()))
    assert COMMITTED.read_text(encoding="utf-8") == generated, (
        "apps/web/openapi.json is out of date with the API models: run make api-schema"
    )


def test_operation_ids_are_the_route_names() -> None:
    paths = create_app(ApiSettings()).openapi()["paths"]
    ids = {path: operations["get"]["operationId"] for path, operations in paths.items()}
    assert ids == OPERATION_IDS


def test_error_responses_use_error_body_and_no_default_validation_schema() -> None:
    schemas = create_app(ApiSettings()).openapi()["components"]["schemas"]
    assert "ErrorBody" in schemas
    assert "HTTPValidationError" not in schemas


def test_response_fields_are_all_required() -> None:
    schemas = create_app(ApiSettings()).openapi()["components"]["schemas"]
    for name, schema in schemas.items():
        assert set(schema["required"]) == set(schema["properties"]), name
