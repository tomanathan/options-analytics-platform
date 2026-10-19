import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from oap.api.main import create_app
from oap.api.settings import ApiSettings
from tests.api.gold import LATEST, GoldFixture

LOCK_MESSAGE = (
    'IO Error: Could not set lock on file "/x/oap.duckdb": '
    "Conflicting lock is held in /usr/bin/python3 (PID 1) by user dbt. See also "
    "https://duckdb.org/docs/connect/concurrency"
)
HOLD_WRITE_LOCK = (
    "import duckdb, sys, time\n"
    "c = duckdb.connect(sys.argv[1])\n"
    "print('ready', flush=True)\n"
    "time.sleep(60)\n"
)


@pytest.fixture
def copy(gold: GoldFixture, tmp_path: Path) -> Path:
    """A private copy of the fixture database, so a test can touch its mtime."""
    target = tmp_path / "copy.duckdb"
    shutil.copy(gold.path, target)
    return target


@pytest.fixture
def copy_client(copy: Path, tmp_path: Path) -> Iterator[TestClient]:
    settings = ApiSettings(duckdb_path=copy, web_dist=tmp_path / "dist")
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _busy(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    attempts: list[int] = []

    def refuse(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        attempts.append(1)
        raise duckdb.IOException(LOCK_MESSAGE)

    monkeypatch.setattr(duckdb, "connect", refuse)
    return attempts


def _touch(path: Path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))


def test_a_locked_file_is_a_503_with_retry_after(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = _busy(monkeypatch)
    response = client.get("/api/underlyings")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "15"
    body = response.json()
    assert body["code"] == "database_busy"
    assert body["detail"] == (
        "The DuckDB file is locked by a writer (dbt_build or score_spreads). Retry shortly."
    )
    assert attempts


def test_other_io_errors_are_not_reported_as_busy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        raise duckdb.IOException("IO Error: disk on fire")

    monkeypatch.setattr(duckdb, "connect", broken)
    with pytest.raises(duckdb.IOException):
        client.get("/api/underlyings")


def test_a_real_writer_lock_is_a_503_and_clears_when_the_writer_exits(
    copy: Path, copy_client: TestClient
) -> None:
    writer = subprocess.Popen(
        [sys.executable, "-c", HOLD_WRITE_LOCK, str(copy)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert writer.stdout is not None
        assert writer.stdout.readline().strip() == "ready"
        response = copy_client.get("/api/underlyings")
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "15"
        assert response.json()["code"] == "database_busy"
        health = copy_client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["db"] == "busy"
    finally:
        writer.terminate()
        writer.wait(timeout=30)
    after = copy_client.get("/api/underlyings")
    assert after.status_code == 200
    assert copy_client.get("/healthz").json()["db"] == "ok"


def test_a_warm_session_is_served_stale_while_the_writer_holds_the_lock(
    copy: Path, copy_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"/api/underlyings/SPY/sessions/{LATEST.isoformat()}/distribution"
    warm = copy_client.get(url)
    assert warm.status_code == 200
    assert "X-OAP-Data-Stale" not in warm.headers
    _touch(copy)
    attempts = _busy(monkeypatch)
    stale = copy_client.get(url)
    assert stale.status_code == 200
    assert stale.headers["X-OAP-Data-Stale"] == "1"
    assert stale.json() == warm.json()
    assert attempts
    health = copy_client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["db"] == "busy"


def test_an_uncached_item_is_a_503_even_when_other_data_is_warm(
    copy: Path, copy_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert copy_client.get("/api/underlyings").status_code == 200
    _touch(copy)
    _busy(monkeypatch)
    assert copy_client.get("/api/underlyings").headers["X-OAP-Data-Stale"] == "1"
    unseen = copy_client.get("/api/underlyings/XLF/sessions")
    assert unseen.status_code == 503
    assert unseen.json()["code"] == "database_busy"
    assert unseen.headers["Retry-After"] == "15"


def test_data_refreshes_once_the_lock_is_released(
    copy: Path, copy_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "/api/underlyings"
    assert copy_client.get(url).status_code == 200
    _touch(copy)
    with monkeypatch.context() as patch:
        _busy(patch)
        assert copy_client.get(url).headers["X-OAP-Data-Stale"] == "1"
    fresh = copy_client.get(url)
    assert fresh.status_code == 200
    assert "X-OAP-Data-Stale" not in fresh.headers


def test_a_missing_file_is_a_503_without_retry_after(tmp_path: Path) -> None:
    settings = ApiSettings(duckdb_path=tmp_path / "absent.duckdb", web_dist=tmp_path / "dist")
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/api/underlyings")
        assert response.status_code == 503
        assert response.json()["code"] == "database_missing"
        assert "make dbt-build-local" in response.json()["detail"]
        assert "Retry-After" not in response.headers
        health = test_client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["db"] == "missing"
        assert health.json()["status"] == "ok"


def test_a_database_without_the_gold_schema_is_a_503(tmp_path: Path) -> None:
    path = tmp_path / "empty.duckdb"
    duckdb.connect(str(path)).close()
    settings = ApiSettings(duckdb_path=path, web_dist=tmp_path / "dist")
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/api/underlyings")
        assert response.status_code == 503
        assert response.json()["code"] == "gold_missing"
        assert test_client.get("/healthz").status_code == 200
