from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oap.api.main import create_app
from oap.api.settings import ApiSettings
from tests.api.gold import GoldFixture

INDEX = "<!doctype html><title>oap explorer</title><div id=root></div>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('oap')", encoding="utf-8")
    return root


@pytest.fixture
def built(gold: GoldFixture, dist: Path) -> TestClient:
    return TestClient(create_app(ApiSettings(duckdb_path=gold.path, web_dist=dist)))


def test_the_root_and_client_routes_return_the_app_shell(built: TestClient) -> None:
    for path in ("/", "/landscape", "/spreads", "/spreads/anything/deep"):
        response = built.get(path)
        assert response.status_code == 200, path
        assert response.text == INDEX


def test_assets_are_served_as_files(built: TestClient) -> None:
    response = built.get("/assets/app.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_an_unknown_api_path_is_a_json_404_not_the_app_shell(built: TestClient) -> None:
    for path in ("/api/nope", "/api/underlyings/SPY/nope", "/api"):
        response = built.get(path)
        assert response.status_code == 404, path
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["code"] == "not_found"


def test_api_and_healthz_still_win_over_the_static_mount(built: TestClient) -> None:
    assert built.get("/healthz").json()["status"] == "ok"
    assert built.get("/api/underlyings").status_code == 200


def test_without_a_build_the_root_is_a_json_hint(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "make web-build" in response.json()["detail"]
    assert client.get("/spreads").status_code == 404
