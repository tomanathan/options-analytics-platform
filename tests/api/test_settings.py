from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oap.api.main import create_app
from oap.api.settings import ApiSettings


def test_defaults() -> None:
    settings = ApiSettings.from_env({})
    assert settings.duckdb_path == Path(".dbt-local/oap.duckdb")
    assert settings.web_dist == Path("apps/web/dist")
    assert settings.retry_after_s == 15
    assert settings.quotes_cache == 3
    assert settings.session_cache == 256
    assert dict(settings.duckdb_config) == {
        "threads": "2",
        "memory_limit": "512MB",
        "access_mode": "READ_ONLY",
    }
    assert settings.cors_origins == ()


def test_environment_overrides() -> None:
    settings = ApiSettings.from_env(
        {
            "OAP_DUCKDB_PATH": "/data/oap.duckdb",
            "OAP_WEB_DIST": "/srv/web",
            "OAP_API_CORS_ORIGINS": " http://localhost:5173 , http://127.0.0.1:5173,, ",
        }
    )
    assert settings.duckdb_path == Path("/data/oap.duckdb")
    assert settings.web_dist == Path("/srv/web")
    assert settings.cors_origins == ("http://localhost:5173", "http://127.0.0.1:5173")


def test_reads_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAP_DUCKDB_PATH", "/from/env.duckdb")
    monkeypatch.delenv("OAP_API_CORS_ORIGINS", raising=False)
    assert ApiSettings.from_env().duckdb_path == Path("/from/env.duckdb")


def test_settings_are_frozen_and_do_not_share_the_duckdb_config() -> None:
    first, second = ApiSettings(), ApiSettings()
    assert first.duckdb_config is not second.duckdb_config
    with pytest.raises(AttributeError):
        first.retry_after_s = 1  # type: ignore[misc]


def test_cors_is_off_unless_origins_are_configured(tmp_path: Path) -> None:
    plain = TestClient(create_app(ApiSettings(duckdb_path=tmp_path / "x", web_dist=tmp_path)))
    response = plain.get("/healthz", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in response.headers
    enabled = ApiSettings(
        duckdb_path=tmp_path / "x", web_dist=tmp_path, cors_origins=("http://localhost:5173",)
    )
    response = TestClient(create_app(enabled)).get(
        "/healthz", headers={"Origin": "http://localhost:5173"}
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    blocked = TestClient(create_app(enabled)).get(
        "/healthz", headers={"Origin": "http://evil.example"}
    )
    assert "access-control-allow-origin" not in blocked.headers
