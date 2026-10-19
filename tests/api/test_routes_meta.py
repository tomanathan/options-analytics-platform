from datetime import date

import pytest
from fastapi.testclient import TestClient

from tests.api.gold import LATEST, SESSIONS, GoldFixture


def test_healthz_reports_the_database(client: TestClient, gold: GoldFixture) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["db_path"] == gold.path.name
    assert body["last_good_signature_at"] is None
    client.get("/api/underlyings")
    assert client.get("/healthz").json()["last_good_signature_at"] is not None


def test_underlyings_are_sorted_with_session_counts(client: TestClient) -> None:
    response = client.get("/api/underlyings")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_session"] == LATEST.isoformat()
    assert [u["symbol"] for u in body["underlyings"]] == ["SPY", "XLF"]
    spy = body["underlyings"][0]
    assert spy == {
        "symbol": "SPY",
        "sector": "Index",
        "first_session": SESSIONS[0].isoformat(),
        "last_session": LATEST.isoformat(),
        "n_sessions": 3,
    }
    assert "X-OAP-Data-Stale" not in response.headers


def test_calibration_summary_matches_the_fixture(client: TestClient, gold: GoldFixture) -> None:
    body = client.get("/api/calibration/summary").json()
    assert body["map_id"] == "production"
    assert body["n_samples"] == gold.production.n_samples
    assert body["train_max_expiration"] == date(2024, 3, 6).isoformat()
    assert body["first_test_year"] == 2021
    assert (body["n_predictions"], body["n_snapshots"], body["n_clusters"]) == (1000, 120, 40)
    order = [(m["metric"], m["variant"]) for m in body["metrics"]]
    assert order == [
        ("brier_score", "raw"),
        ("brier_score", "calibrated"),
        ("brier_score", "delta"),
        ("expected_calibration_error", "raw"),
        ("expected_calibration_error", "calibrated"),
        ("log_loss", "raw"),
        ("log_loss", "calibrated"),
    ]
    ece = {m["variant"]: m for m in body["metrics"] if m["metric"] == "expected_calibration_error"}
    assert ece["raw"]["value"] == pytest.approx(0.0352)
    assert ece["calibrated"]["value"] == pytest.approx(0.0167)
    brier = {m["variant"]: m for m in body["metrics"] if m["metric"] == "brier_score"}
    assert brier["delta"]["value"] == pytest.approx(0.1293 - 0.1267)
    assert ece["raw"]["ci_low"] == pytest.approx(0.0252)
    assert ece["raw"]["ci_high"] == pytest.approx(0.0452)
