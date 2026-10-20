import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from oap.analytics.views import PRESETS
from oap.api import models
from oap.api.models import (
    KindBest,
    OutcomeCell,
    OutcomeMapResponse,
    OutcomeRow,
    StructureRow,
    StructuresResponse,
    TailInfo,
    Verdict,
    ViewInfo,
)
from oap.engine.structures import REASON_TEMPLATES
from tests.api.gold import FAR_EXPIRY, LATEST, NEAR_EXPIRY, SESSIONS, THIN_EXPIRY

URL = f"/api/structures/SPY/{LATEST.isoformat()}"
BANNED = ("buy", "sell", "recommend", "should")
NEW_MODELS: tuple[type[BaseModel], ...] = (
    TailInfo,
    ViewInfo,
    StructureRow,
    KindBest,
    models.DominanceSegment,
    Verdict,
    StructuresResponse,
    models.PresetInfo,
    OutcomeCell,
    OutcomeRow,
    OutcomeMapResponse,
)


def _ok(client: TestClient, url: str = URL, **params: object) -> dict[str, Any]:
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _error(client: TestClient, status: int, url: str = URL, **params: object) -> dict[str, Any]:
    response = client.get(url, params=params)
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_preset_scores_the_default_expiration(client: TestClient) -> None:
    body = _ok(client, preset="up_moderate")
    assert body["expiration"] == FAR_EXPIRY.isoformat()
    assert body["fill"] == "natural"
    assert body["map_id"] == "production"
    assert body["view"]["preset"] == "up_moderate"
    assert body["view"]["prob"] == pytest.approx(0.30, abs=1e-9)
    assert 0 < body["view"]["prob_market"] < 1
    assert len(body["grid"]) == len(body["density"]) == 161
    kinds = [k["kind"] for k in body["kinds"]]
    assert {"long_call", "bull_call_spread", "bull_put_spread"} <= set(kinds)
    assert all(len(k["curve"]) == 161 for k in body["kinds"])
    assert "curve" not in body["ranking"][0]
    assert len(body["ranking"]) == min(25, body["n_qualifying"])
    assert body["n_structures"] >= body["n_qualifying"] > 0
    assert body["dominance"][0]["from"] == body["grid"][0]
    assert body["verdict"]["reason"]
    assert body["tails"]["sigma_lo"] == pytest.approx(0.30)


def test_custom_bounds_are_fractions_of_the_close(client: TestClient) -> None:
    body = _ok(client, lo=1.05)
    close = body["underlying_close"]
    assert body["view"]["preset"] is None
    assert body["view"]["lo"] == pytest.approx(1.05 * close)
    assert body["view"]["hi"] is None
    assert body["view"]["lo_moneyness"] == pytest.approx(1.05)
    outside = _ok(client, lo=0.95, hi=1.05, outside="true")
    assert outside["view"]["outside"] is True
    inside = _ok(client, lo=0.95, hi=1.05)
    assert outside["view"]["prob"] == pytest.approx(1 - inside["view"]["prob"], abs=1e-12)


def test_query_options(client: TestClient) -> None:
    loose = _ok(client, preset="flat", fill="mid", min_pop_given=0.5)
    mid = _ok(client, preset="flat", fill="mid", limit=3, min_pop_given=0.8)
    assert mid["fill"] == "mid"
    assert len(mid["ranking"]) <= 3
    assert all(r["prob_profit_given_view"] >= 0.8 for r in mid["ranking"])
    assert mid["n_qualifying"] <= loose["n_qualifying"]
    assert mid["n_structures"] == loose["n_structures"]
    near = _ok(client, preset="flat", expiration=NEAR_EXPIRY.isoformat())
    assert near["expiration"] == NEAR_EXPIRY.isoformat()
    earlier = _ok(client, f"/api/structures/SPY/{SESSIONS[0].isoformat()}", preset="up")
    assert earlier["map_id"] == "fold_2024"
    production = _ok(
        client, f"/api/structures/SPY/{SESSIONS[0].isoformat()}", preset="up", map="production"
    )
    assert production["map_id"] == "production"
    assert production["look_ahead"] is True


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, "view_required"),
        ({"outside": "true"}, "view_required"),
        ({"lo": 1.1, "hi": 1.0}, "view_invalid"),
        ({"preset": "up", "expiration": THIN_EXPIRY.isoformat()}, "no_distribution"),
        ({"preset": "sideways"}, "invalid"),
        ({"preset": "up", "fill": "best"}, "invalid"),
        ({"preset": "up", "limit": 0}, "invalid"),
        ({"preset": "up", "min_pop_given": 1.5}, "invalid"),
        ({"lo": -1.0}, "invalid"),
    ],
)
def test_unprocessable_requests(client: TestClient, params: dict[str, object], code: str) -> None:
    response = client.get(URL, params=params)
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == code
    if code == "no_distribution":
        assert "too_few_puts" in body["detail"]


@pytest.mark.parametrize(
    "url",
    [
        f"/api/structures/QQQ/{LATEST.isoformat()}",
        "/api/structures/SPY/2024-03-07",
    ],
)
def test_unknown_symbol_or_session(client: TestClient, url: str) -> None:
    assert _error(client, 404, url, preset="up")["code"] == "not_found"


def test_unknown_expiration(client: TestClient) -> None:
    assert _error(client, 404, preset="up", expiration="2024-05-17")["code"] == "not_found"


def test_books_are_cached_per_fill(client: TestClient) -> None:
    _ok(client, preset="up")
    _ok(client, preset="down")
    store = client.app.state.store  # type: ignore[attr-defined]
    assert len(store._books) == 1
    _ok(client, preset="up", fill="mid")
    assert len(store._books) == 2


def test_outcome_map(client: TestClient) -> None:
    body = _ok(client, "/api/structures/map")
    assert body["session"] == LATEST.isoformat()
    assert body["target_dte"] == 35
    assert body["map_id"] == "production"
    assert [p["id"] for p in body["presets"]] == [p.id for p in PRESETS]
    assert [p["label"] for p in body["presets"]] == [p.label for p in PRESETS]
    assert [r["symbol"] for r in body["rows"]] == ["SPY", "XLF"]
    for row in body["rows"]:
        assert row["expiration"] == FAR_EXPIRY.isoformat()
        assert [c["preset"] for c in row["cells"]] == [p.id for p in PRESETS]
    cell = body["rows"][0]["cells"][1]
    single = _ok(client, preset=cell["preset"])
    assert single["verdict"]["best_kind"] == cell["best_kind"]
    assert single["verdict"]["advantage"] == pytest.approx(cell["advantage"])
    assert single["view"]["prob"] == pytest.approx(cell["prob"])


def test_outcome_map_options(client: TestClient) -> None:
    body = _ok(
        client,
        "/api/structures/map",
        session=SESSIONS[0].isoformat(),
        target_dte=7,
        fill="mid",
        map="walk_forward",
        min_pop_given=0.6,
    )
    assert body["session"] == SESSIONS[0].isoformat()
    assert body["fill"] == "mid"
    assert body["map_id"] == "fold_2024"
    assert {r["expiration"] for r in body["rows"]} == {NEAR_EXPIRY.isoformat()}
    assert _error(client, 404, "/api/structures/map", session="2030-01-02")["code"] == "not_found"
    assert _error(client, 422, "/api/structures/map", target_dte=200)["code"] == "invalid"
    assert _error(client, 422, "/api/structures/map", session="yesterday")["code"] == "invalid"


def _texts() -> list[tuple[str, str]]:
    found = [(f"template {k}", v) for k, v in REASON_TEMPLATES.items()]
    for model in NEW_MODELS:
        found.append((model.__name__, model.__doc__ or ""))
        for name, field in model.model_fields.items():
            found.append((f"{model.__name__}.{name}", field.description or ""))
    found.extend((f"preset {p.id}", p.label) for p in PRESETS)
    return found


def test_no_new_text_advises_a_trade(client: TestClient) -> None:
    texts = _texts()
    for preset in [p.id for p in PRESETS]:
        texts.append((preset, _ok(client, preset=preset)["verdict"]["reason"]))
    for where, text in texts:
        words = re.findall(r"[a-z]+", text.lower())
        for banned in BANNED:
            assert not any(word.startswith(banned) for word in words), (where, text)


def test_every_new_field_has_a_description() -> None:
    for model in NEW_MODELS:
        for name, field in model.model_fields.items():
            assert field.description, f"{model.__name__}.{name}"
