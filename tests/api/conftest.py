from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oap.api.main import create_app
from oap.api.settings import ApiSettings
from tests.api.gold import GoldFixture, build_gold


@pytest.fixture(scope="module")
def gold(tmp_path_factory: pytest.TempPathFactory) -> GoldFixture:
    """A gold DuckDB file built once per test module."""
    return build_gold(tmp_path_factory.mktemp("gold") / "oap.duckdb")


@pytest.fixture
def settings(gold: GoldFixture, tmp_path: Path) -> ApiSettings:
    """Settings that point at the fixture database and a web dist that does not exist."""
    return ApiSettings(duckdb_path=gold.path, web_dist=tmp_path / "dist")


@pytest.fixture
def client(settings: ApiSettings) -> Iterator[TestClient]:
    """A client on a fresh application, so each test starts with empty caches."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client
