from datetime import date
from urllib.parse import quote

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.sample import chain_cdf
from oap.engine.calibration import apply_calibration
from oap.engine.conventions import dte_years
from tests.api.gold import LATEST, GoldFixture

Row = dict[str, object]


def _rows(client: TestClient, **params: object) -> list[Row]:
    response = client.get("/api/spreads", params=params)
    assert response.status_code == 200, response.text
    rows: list[Row] = response.json()["rows"]
    return rows


def _detail_url(key: str) -> str:
    return "/api/spreads/" + quote(key, safe="")


def test_default_is_the_eligible_spreads_in_rank_order(
    client: TestClient, gold: GoldFixture
) -> None:
    body = client.get("/api/spreads").json()
    eligible = int(gold.scores["eligible"].sum())
    assert body["source"] == "gold"
    assert body["as_of"] == LATEST.isoformat()
    assert body["total"] == len(gold.scores)
    assert body["matched"] == eligible
    assert len(body["rows"]) == eligible
    assert body["min_prob_profit"] == DEFAULT_CONFIG.min_prob_profit
    assert body["underlyings"] == ["SPY", "XLF"]
    assert body["expirations"] == ["2024-03-28", "2024-04-19"]
    assert all(row["eligible"] for row in body["rows"])
    assert [row["rank"] for row in body["rows"]] == list(range(1, eligible + 1))


def test_eligible_only_false_returns_everything_ranked_first(
    client: TestClient, gold: GoldFixture
) -> None:
    body = client.get("/api/spreads", params={"eligible_only": "false"}).json()
    assert body["matched"] == len(gold.scores)
    ranks = [row["rank"] for row in body["rows"]]
    ranked = [r for r in ranks if r is not None]
    assert ranks[: len(ranked)] == ranked == sorted(ranked)
    assert all(r is None for r in ranks[len(ranked) :])
    tail = [row["annualised_roc"] for row in body["rows"][len(ranked) :]]
    values = [v for v in tail if v is not None]
    assert values == sorted(values, reverse=True)


def test_each_filter_on_its_own(client: TestClient, gold: GoldFixture) -> None:
    scores = gold.scores
    eligible = scores.loc[scores["eligible"].astype(bool)]
    xlf = _rows(client, underlying="XLF")
    assert {r["underlying"] for r in xlf} == {"XLF"}
    assert len(xlf) == int((eligible["underlying"] == "XLF").sum())
    both = _rows(client, underlying=["SPY", "XLF"])
    assert len(both) == len(eligible)

    one_day = date(2024, 4, 19)
    far = _rows(client, expiration="2024-04-19")
    assert len(far) == int((eligible["expiration"] == one_day).sum())
    assert {r["expiration"] for r in far} == {"2024-04-19"}

    widths = eligible["width"].to_numpy()
    cut = float(np.median(widths))
    wide = _rows(client, min_width=cut)
    assert len(wide) == int((widths >= cut).sum())
    assert all(float(str(r["width"])) >= cut for r in wide)
    narrow = _rows(client, max_width=cut)
    assert len(narrow) == int((widths <= cut).sum())

    pop = _rows(client, min_pop=0.7)
    assert len(pop) == int((eligible["prob_profit"] >= 0.7).sum())
    assert all(float(str(r["prob_profit"])) >= 0.7 for r in pop)

    credit = _rows(client, min_credit=0.5)
    assert len(credit) == int((eligible["credit"] >= 0.5).sum())

    assert len(_rows(client, limit=3)) == 3


def test_limit_does_not_change_the_matched_count(client: TestClient) -> None:
    body = client.get("/api/spreads", params={"limit": 2}).json()
    assert len(body["rows"]) == 2
    assert body["matched"] > 2


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 5001},
        {"min_pop": 1.5},
        {"min_pop": -0.1},
        {"min_credit": -1},
        {"expiration": "soon"},
        {"underlying": "spy"},
    ],
)
def test_bad_filters_are_rejected(client: TestClient, params: dict[str, object]) -> None:
    response = client.get("/api/spreads", params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid"


def test_detail_by_encoded_key_matches_the_list_row(client: TestClient) -> None:
    first = _rows(client, limit=1)[0]
    key = str(first["spread_key"])
    assert "|" in key
    response = client.get(_detail_url(key))
    assert response.status_code == 200
    detail = response.json()
    for name, value in first.items():
        assert detail[name] == value, name
    assert detail["trade_date"] == LATEST.isoformat()
    assert detail["map_id"] == "production"
    assert detail["calibrated"] is True


def test_calibrated_probability_of_profit_is_one_minus_the_cdf_at_the_breakeven(
    client: TestClient, gold: GoldFixture
) -> None:
    for row in _rows(client, limit=5):
        detail = client.get(_detail_url(str(row["spread_key"]))).json()
        quotes = gold.quotes
        chain = quotes.loc[
            (quotes["underlying"] == detail["underlying"])
            & (quotes["trade_date"] == pd.Timestamp(detail["trade_date"]))
            & (quotes["expiration"] == pd.Timestamp(detail["expiration"]))
        ]
        cdf = chain_cdf(
            chain,
            years=dte_years(
                date.fromisoformat(detail["trade_date"]), date.fromisoformat(detail["expiration"])
            ),
            rate=DEFAULT_CONFIG.risk_free_apy,
        )
        assert cdf is not None
        cal = apply_calibration(cdf, gold.production)
        assert 1.0 - cal.prob_below(detail["breakeven"]) == pytest.approx(
            detail["prob_profit"], abs=1e-9
        )
        assert detail["regions"]["prob_profit"]["calibrated"] == pytest.approx(
            detail["prob_profit"], abs=1e-9
        )
        assert detail["regions"]["prob_profit"]["raw"] == pytest.approx(
            detail["prob_profit_raw"], abs=1e-9
        )
        assert detail["regions"]["prob_max_loss"]["calibrated"] == pytest.approx(
            detail["prob_max_loss"], abs=1e-9
        )
        parts = detail["regions"]
        for variant in ("raw", "calibrated"):
            total = sum(
                parts[name][variant]
                for name in ("prob_max_loss", "prob_partial_loss", "prob_profit")
            )
            assert total == pytest.approx(1.0, abs=1e-9)
        assert detail["knot_range"] == [cdf.strikes[0], cdf.strikes[-1]]


def test_payoff_curve_is_flat_beyond_the_strikes(client: TestClient) -> None:
    detail = client.get(_detail_url(str(_rows(client, limit=1)[0]["spread_key"]))).json()
    payoff = detail["payoff"]
    prices = [p["price"] for p in payoff]
    assert len(payoff) in range(160, 170)
    assert prices == sorted(prices)
    assert len(set(prices)) == len(prices)
    for point in payoff:
        if point["price"] >= detail["short_strike"]:
            assert point["payoff"] == pytest.approx(detail["credit"])
        if point["price"] <= detail["long_strike"]:
            assert point["payoff"] == pytest.approx(-detail["max_loss"])
    at_breakeven = next(p for p in payoff if p["price"] == pytest.approx(detail["breakeven"]))
    assert at_breakeven["payoff"] == pytest.approx(0.0, abs=1e-9)
    assert min(prices) <= detail["long_strike"] - 2 * detail["width"] + 1e-9
    assert max(prices) >= detail["short_strike"] + 2 * detail["width"] - 1e-9
    assert (
        len(detail["density_mid"])
        == len(detail["density_raw"])
        == len(detail["density_calibrated"])
    )


def test_an_infinite_annualised_return_serialises_as_null(
    client: TestClient, gold: GoldFixture
) -> None:
    detail = client.get(_detail_url(gold.inf_key))
    assert detail.status_code == 200
    assert detail.json()["annualised_roc"] is None
    assert "Infinity" not in detail.text
    assert "NaN" not in detail.text
    listing = client.get("/api/spreads")
    assert "Infinity" not in listing.text
    row = next(r for r in listing.json()["rows"] if r["spread_key"] == gold.inf_key)
    assert row["annualised_roc"] is None


def test_unknown_spread_key_is_404(client: TestClient) -> None:
    response = client.get(_detail_url("SPY|2024-03-06|2024-03-28|1.000|0.500"))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_the_key_is_matched_as_data_not_sql(client: TestClient) -> None:
    response = client.get(_detail_url("x' OR '1'='1"))
    assert response.status_code == 404
