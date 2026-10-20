import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oap.api.errors import (
    BUSY_DETAIL,
    MISSING_DETAIL,
    ApiError,
    DatabaseBusy,
    DatabaseMissing,
    GoldMissing,
    NotFound,
    Unprocessable,
)
from oap.api.handlers import install_error_handlers


def _client(error: ApiError) -> TestClient:
    app = FastAPI()
    install_error_handlers(app, retry_after_s=7)

    @app.get("/boom")
    def boom() -> None:
        raise error

    @app.get("/typed/{n}")
    def typed(n: int) -> int:
        return n

    return TestClient(app)


@pytest.mark.parametrize(
    ("error", "status", "code", "detail"),
    [
        (DatabaseBusy("locked"), 503, "database_busy", BUSY_DETAIL),
        (DatabaseMissing("absent"), 503, "database_missing", MISSING_DETAIL),
        (GoldMissing("no spread_scores"), 503, "gold_missing", "no spread_scores"),
        (NotFound("unknown underlying: ZZZ"), 404, "not_found", "unknown underlying: ZZZ"),
        (Unprocessable("view_invalid", "bad view"), 422, "view_invalid", "bad view"),
    ],
)
def test_each_error_becomes_its_status_and_body(
    error: ApiError, status: int, code: str, detail: str
) -> None:
    response = _client(error).get("/boom")
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert detail in body["detail"]
    if code == "database_busy":
        assert response.headers["Retry-After"] == "7"


def test_validation_and_routing_errors_use_the_same_body() -> None:
    client = _client(NotFound("x"))
    invalid = client.get("/typed/abc")
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid"
    assert invalid.json()["detail"].startswith("path.n:")
    missing = client.get("/nowhere")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "No such resource.", "code": "not_found"}


def test_the_errors_module_does_not_need_fastapi() -> None:
    import oap.api.errors as errors

    assert "fastapi" not in errors.__dict__
    assert not hasattr(errors, "install_error_handlers")
