from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from tests.api.gold import (
    FAR_EXPIRY,
    LATEST,
    NEAR_EXPIRY,
    SESSIONS,
    SHORT_EXPIRY,
    THIN_EXPIRY,
    GoldFixture,
)

MAX_BYTES = 64 * 1024


def _url(session: date, tail: str, symbol: str = "SPY") -> str:
    return f"/api/underlyings/{symbol}/sessions/{session.isoformat()}/{tail}"


def test_sessions_are_ascending_with_the_close(client: TestClient, gold: GoldFixture) -> None:
    response = client.get("/api/underlyings/SPY/sessions")
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "SPY"
    assert [s["session"] for s in body["sessions"]] == [d.isoformat() for d in SESSIONS]
    assert [s["underlying_close"] for s in body["sessions"]] == [500.0, 503.0, 498.0]
    first = body["sessions"][0]
    assert first["n_expirations"] == 4
    assert first["n_quotes"] == int((gold.quotes["underlying"] == "SPY").sum() / 3)
    assert first["atm_iv"] == pytest.approx(0.30)


def test_chain_is_grouped_and_ordered(client: TestClient) -> None:
    body = client.get(_url(LATEST, "chain")).json()
    assert body["symbol"] == "SPY"
    assert body["session"] == LATEST.isoformat()
    assert body["underlying_close"] == 498.0
    assert [e["expiration"] for e in body["expirations"]] == [
        d.isoformat() for d in (SHORT_EXPIRY, NEAR_EXPIRY, FAR_EXPIRY, THIN_EXPIRY)
    ]
    assert [e["dte_days"] for e in body["expirations"]] == [2, 22, 44, 107]
    for expiry in body["expirations"]:
        keys = [(q["strike"], q["option_right"]) for q in expiry["quotes"]]
        assert keys == sorted(keys)
    thin = body["expirations"][-1]["quotes"]
    assert sum(q["option_right"] == "P" for q in thin) == 3


def test_distribution_has_the_documented_shape(client: TestClient) -> None:
    body = client.get(_url(LATEST, "distribution")).json()
    assert body["map_choice"] == "auto"
    assert body["map_id"] == "production"
    assert body["map_is_identity"] is False
    assert body["look_ahead"] is False
    assert body["risk_free_apy"] == 0.045
    by_expiry = {e["expiration"]: e for e in body["expirations"]}
    near = by_expiry[NEAR_EXPIRY.isoformat()]
    curve = near["curve"]
    n = near["n_knots"]
    assert near["unavailable_reason"] is None
    assert near["years"] == pytest.approx(22 / 365)
    for key in ("knots", "moneyness", "cdf", "raw_cdf", "cdf_calibrated"):
        assert len(curve[key]) == n
    for key in ("density_mid", "density", "density_calibrated"):
        assert len(curve[key]) == n - 1
    assert curve["cdf_calibrated"] != curve["cdf"]
    thin = by_expiry[THIN_EXPIRY.isoformat()]
    assert thin["curve"] is None
    assert thin["unavailable_reason"] == "too_few_puts"
    short = by_expiry[SHORT_EXPIRY.isoformat()]
    assert short["short_dated"] is True
    assert short["settlement_close"] == 497.0
    assert 0.0 <= short["prob_below_settlement"] <= 1.0


def test_map_choice_selects_the_map(client: TestClient) -> None:
    session = SESSIONS[1]
    auto = client.get(_url(session, "distribution")).json()
    assert auto["map_id"] == "fold_2024"
    assert auto["map_is_identity"] is True
    assert auto["look_ahead"] is False
    production = client.get(_url(session, "distribution"), params={"map": "production"}).json()
    assert production["map_choice"] == "production"
    assert production["map_id"] == "production"
    assert production["look_ahead"] is True
    assert production["map_train_max_expiration"] == "2024-03-06"
    walk = client.get(_url(LATEST, "distribution"), params={"map": "walk_forward"}).json()
    assert walk["map_id"] == "fold_2024"
    assert client.get(_url(session, "distribution"), params={"map": "x"}).status_code == 422


def test_heatmap_shape(client: TestClient) -> None:
    body = client.get(_url(LATEST, "heatmap")).json()
    assert body["map_id"] == "production"
    assert len(body["moneyness"]) == 41
    assert body["moneyness"][0] == 0.8
    assert body["moneyness"][-1] == 1.2
    assert body["backtest_grid"][0] == 0.8
    assert len(body["backtest_grid"]) == 13
    assert [r["expiration"] for r in body["rows"]] == [
        d.isoformat() for d in (SHORT_EXPIRY, NEAR_EXPIRY, FAR_EXPIRY)
    ]
    for row in body["rows"]:
        assert len(row["target_strikes"]) == len(row["prob_below"]) == 41
        assert len(row["prob_below_calibrated"]) == 41
        assert any(p is not None for p in row["prob_below"])
        assert row["forward_moneyness"] == pytest.approx(1.0, abs=0.05)


@pytest.mark.parametrize(
    ("url", "status", "code"),
    [
        ("/api/underlyings/ZZZ/sessions", 404, "not_found"),
        ("/api/underlyings/ZZZ/sessions/2024-03-06/chain", 404, "not_found"),
        ("/api/underlyings/SPY/sessions/2024-03-09/chain", 404, "not_found"),
        ("/api/underlyings/SPY/sessions/2024-03-09/distribution", 404, "not_found"),
        ("/api/underlyings/SPY/sessions/2024-03-09/heatmap", 404, "not_found"),
        ("/api/underlyings/spy/sessions", 422, "invalid"),
        ("/api/underlyings/SPY%3B/sessions", 422, "invalid"),
        ("/api/underlyings/TOOLONGSYMBOL/sessions", 422, "invalid"),
        ("/api/underlyings/SPY/sessions/yesterday/chain", 422, "invalid"),
        ("/api/underlyings/SPY/sessions/2024-13-45/chain", 422, "invalid"),
    ],
)
def test_unknown_and_invalid_requests(client: TestClient, url: str, status: int, code: str) -> None:
    response = client.get(url)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert isinstance(response.json()["detail"], str)


def test_a_symbol_cannot_inject_sql(client: TestClient) -> None:
    response = client.get("/api/underlyings/SPY'%20OR%20'1'='1/sessions")
    assert response.status_code == 422
    assert client.get("/api/underlyings").status_code == 200


def test_every_fixture_response_is_small(client: TestClient) -> None:
    for tail in ("chain", "distribution", "heatmap"):
        raw = client.get(_url(LATEST, tail), headers={"Accept-Encoding": "identity"})
        assert raw.status_code == 200
        assert len(raw.content) < MAX_BYTES, tail


def test_responses_are_gzipped_when_large(client: TestClient) -> None:
    response = client.get(_url(LATEST, "chain"), headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"


def test_a_second_call_for_the_same_session_opens_no_connection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = duckdb.connect
    opened: list[str] = []

    def counting(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        opened.append("connect")
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(duckdb, "connect", counting)
    assert client.get(_url(LATEST, "distribution")).status_code == 200
    first = len(opened)
    assert first >= 1
    for tail in ("distribution", "chain", "heatmap"):
        assert client.get(_url(LATEST, tail)).status_code == 200
    assert client.get("/api/underlyings/SPY/sessions").status_code == 200
    assert client.get(_url(SESSIONS[0], "distribution")).status_code == 200
    assert len(opened) == first


def test_connections_are_opened_read_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = duckdb.connect
    seen: list[dict[str, object]] = []

    def spying(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        seen.append(dict(kwargs))
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(duckdb, "connect", spying)
    client.get("/api/underlyings")
    assert seen
    assert all(call["read_only"] is True for call in seen)
