from datetime import date

import numpy as np
import pandas as pd
import pytest

from oap.analytics.config import DEFAULT_CONFIG, PRODUCTION_MAP_ID, AnalyticsConfig
from oap.analytics.sample import chain_cdf
from oap.analytics.scoring import SPREAD_COLUMNS, latest_session, score_latest_session
from oap.engine.calibration import CalibrationMap
from oap.engine.spread_scoring import PutCreditSpread, score_spread
from tests.analytics.frames import lognormal_quotes

RATE = DEFAULT_CONFIG.risk_free_apy
SPY_STRIKES = np.arange(80.0, 121.0, 1.0)
AAPL_STRIKES = np.arange(160.0, 221.0, 2.0)


def _quotes() -> pd.DataFrame:
    return pd.concat(
        [
            lognormal_quotes(
                "SPY", date(2024, 1, 5), date(2024, 2, 2), 100.0, 0.25, RATE, SPY_STRIKES
            ),
            lognormal_quotes(
                "SPY", date(2024, 1, 5), date(2024, 2, 16), 100.0, 0.25, RATE, SPY_STRIKES
            ),
            lognormal_quotes(
                "SPY", date(2024, 1, 5), date(2024, 1, 9), 100.0, 0.25, RATE, SPY_STRIKES
            ),
            lognormal_quotes(
                "SPY", date(2024, 1, 4), date(2024, 2, 2), 99.0, 0.25, RATE, SPY_STRIKES
            ),
            lognormal_quotes(
                "AAPL", date(2024, 1, 4), date(2024, 2, 2), 190.0, 0.3, RATE, AAPL_STRIKES
            ),
        ],
        ignore_index=True,
    )


def _tilt() -> CalibrationMap:
    """A fitted-looking map that lowers mid-range probabilities."""
    return CalibrationMap(
        np.array([0.0, 0.2, 0.5, 0.8, 1.0]),
        np.array([0.0, 0.1, 0.3, 0.7, 1.0]),
        n_samples=500,
        is_identity=False,
    )


def _scores(
    cmap: CalibrationMap | None = None, config: AnalyticsConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    latest = latest_session(_quotes(), min_dte_days=config.min_dte_days)
    return score_latest_session(latest, cmap or CalibrationMap.identity(0), config)


def test_latest_session_is_per_underlying_and_drops_short_dte() -> None:
    latest = latest_session(_quotes(), min_dte_days=7)
    spy = latest.loc[latest["underlying"] == "SPY"]
    aapl = latest.loc[latest["underlying"] == "AAPL"]
    assert set(spy["trade_date"]) == {pd.Timestamp("2024-01-05")}
    assert set(aapl["trade_date"]) == {pd.Timestamp("2024-01-04")}
    assert set(spy["expiration"]) == {pd.Timestamp("2024-02-02"), pd.Timestamp("2024-02-16")}
    assert (latest["dte_days"] >= 7).all()
    assert latest.index.tolist() == list(range(len(latest)))


def test_every_row_satisfies_the_spread_invariants() -> None:
    scores = _scores()
    assert tuple(scores.columns) == SPREAD_COLUMNS
    assert len(scores) > 100
    assert set(scores["underlying"]) == {"SPY", "AAPL"}
    assert (scores["long_strike"] < scores["short_strike"]).all()
    assert (scores["credit"] > 0).all()
    assert (scores["credit"] < scores["width"]).all()
    assert (scores["credit"] >= DEFAULT_CONFIG.min_credit).all()
    assert (
        scores["width"] <= DEFAULT_CONFIG.max_width_fraction * scores["underlying_close"] + 1e-9
    ).all()
    np.testing.assert_allclose(scores["max_loss"], scores["width"] - scores["credit"])
    np.testing.assert_allclose(scores["breakeven"], scores["short_strike"] - scores["credit"])
    np.testing.assert_allclose(
        scores["short_moneyness"], scores["short_strike"] / scores["underlying_close"]
    )
    for column in ("prob_profit", "prob_profit_raw", "prob_max_loss", "kelly_fraction"):
        assert scores[column].between(0.0, 1.0).all()
    assert scores["spread_key"].is_unique
    assert (scores["map_id"] == PRODUCTION_MAP_ID).all()
    assert (scores["cash_apy"] == DEFAULT_CONFIG.cash_apy).all()
    assert (scores["risk_free_apy"] == DEFAULT_CONFIG.risk_free_apy).all()
    first = scores.iloc[0]
    assert first["spread_key"] == (
        f"{first['underlying']}|{first['trade_date'].date()}|{first['expiration'].date()}"
        f"|{first['short_strike']:.3f}|{first['long_strike']:.3f}"
    )
    assert scores["dte_days"].isin([29, 28, 42]).all()


def test_identity_map_leaves_probabilities_raw() -> None:
    scores = _scores()
    np.testing.assert_allclose(scores["prob_profit"], scores["prob_profit_raw"], atol=1e-12)
    np.testing.assert_allclose(scores["annualised_roc"], scores["annualised_roc_raw"], atol=1e-9)
    assert not scores["calibrated"].any()


def test_fitted_map_changes_the_calibrated_columns_only() -> None:
    identity = _scores()
    tilted = _scores(_tilt(), config=DEFAULT_CONFIG)
    assert tilted["calibrated"].all()
    assert (tilted["prob_profit"] != tilted["prob_profit_raw"]).any()
    np.testing.assert_array_equal(tilted["prob_profit_raw"], identity["prob_profit_raw"])
    np.testing.assert_array_equal(tilted["credit"], identity["credit"])


def test_scores_equal_score_spread_with_the_calibration_argument() -> None:
    cmap = _tilt()
    scores = _scores(cmap)
    quotes = latest_session(_quotes(), min_dte_days=7)
    for _, row in scores.sample(12, random_state=4).iterrows():
        chain = quotes.loc[
            (quotes["underlying"] == row["underlying"])
            & (quotes["expiration"] == row["expiration"])
        ]
        cdf = chain_cdf(chain, years=row["years"], rate=RATE)
        assert cdf is not None
        spread = PutCreditSpread(
            row["underlying"],
            row["expiration"].date(),
            row["short_strike"],
            row["long_strike"],
            row["credit"],
            row["years"],
        )
        direct = score_spread(spread, cdf, cash_apy=DEFAULT_CONFIG.cash_apy, calibration=cmap)
        plain = score_spread(spread, cdf, cash_apy=DEFAULT_CONFIG.cash_apy)
        assert row["prob_profit"] == pytest.approx(direct.prob_profit, abs=1e-12)
        assert row["prob_max_loss"] == pytest.approx(direct.prob_max_loss, abs=1e-12)
        assert row["expected_payoff"] == pytest.approx(direct.expected_payoff, abs=1e-12)
        assert row["expected_roc"] == pytest.approx(direct.expected_return_on_collateral, abs=1e-12)
        assert row["annualised_roc"] == pytest.approx(direct.annualised_return, abs=1e-9)
        assert row["kelly_fraction"] == pytest.approx(direct.kelly_fraction, abs=1e-12)
        assert row["prob_profit_raw"] == pytest.approx(plain.prob_profit, abs=1e-12)
        assert row["expected_roc_raw"] == pytest.approx(
            plain.expected_return_on_collateral, abs=1e-12
        )
        assert row["extrapolated"] == direct.extrapolated


def test_natural_credit_is_short_bid_minus_long_ask() -> None:
    scores = _scores()
    quotes = latest_session(_quotes(), min_dte_days=7)
    puts = quotes.loc[quotes["option_right"] == "P"].set_index(
        ["underlying", "expiration", "strike"]
    )
    for _, row in scores.sample(10, random_state=1).iterrows():
        short_bid = puts.loc[(row["underlying"], row["expiration"], row["short_strike"]), "bid"]
        long_ask = puts.loc[(row["underlying"], row["expiration"], row["long_strike"]), "ask"]
        assert row["credit_natural"] == pytest.approx(short_bid - long_ask)
        # Mid credit minus the two half-spreads of 0.05 each.
        assert row["credit_natural"] == pytest.approx(row["credit"] - 0.10)


def _expected_eligible(scores: pd.DataFrame, config: AnalyticsConfig) -> pd.Series:
    return (
        ~scores["extrapolated"]
        & (scores["credit_natural"] > 0)
        & (scores["short_strike"] < scores["underlying_close"])
        & (scores["prob_profit"] >= config.min_prob_profit)
    )


@pytest.mark.parametrize(
    "config",
    [
        DEFAULT_CONFIG,
        AnalyticsConfig(min_credit=0.0),
        AnalyticsConfig(min_prob_profit=0.9),
        AnalyticsConfig(min_prob_profit=0.0, max_width_fraction=0.3),
    ],
)
def test_eligibility_and_rank_follow_the_rules(config: AnalyticsConfig) -> None:
    scores = _scores(_tilt(), config)
    expected = _expected_eligible(scores, config)
    assert expected.any()
    assert (~expected).any()
    pd.testing.assert_series_equal(scores["eligible"], expected, check_names=False)
    assert scores["rank"].notna().tolist() == scores["eligible"].tolist()


def test_each_ineligibility_reason_blocks_the_rank() -> None:
    scores = _scores(_tilt(), AnalyticsConfig(min_credit=0.0, min_prob_profit=0.6))
    assert scores["rank"].dtype == "Int64"
    reasons = {
        "extrapolated": scores["extrapolated"],
        "negative natural credit": scores["credit_natural"] <= 0,
        "in the money": scores["short_strike"] >= scores["underlying_close"],
        "low probability": scores["prob_profit"] < 0.6,
    }
    for name, mask in reasons.items():
        assert mask.any(), name
        assert scores.loc[mask, "rank"].isna().all(), name
        assert not scores.loc[mask, "eligible"].any(), name


def test_ranks_are_contiguous_and_follow_rank_spreads_order() -> None:
    scores = _scores(_tilt())
    ranked = scores.loc[scores["rank"].notna()].sort_values("rank")
    k = len(ranked)
    assert k > 10
    assert ranked["rank"].tolist() == list(range(1, k + 1))
    assert ranked["rank"].is_unique
    keys = list(
        zip(
            -ranked["annualised_roc"],
            -ranked["prob_profit"],
            -ranked["short_strike"],
            ranked["long_strike"],
            strict=True,
        )
    )
    assert keys == sorted(keys)
    assert set(ranked["underlying"]) == {"SPY", "AAPL"}


def test_map_id_is_recorded() -> None:
    latest = latest_session(_quotes(), min_dte_days=7)
    scores = score_latest_session(latest, _tilt(), map_id="fold_2024")
    assert (scores["map_id"] == "fold_2024").all()


def test_short_dte_and_bad_close_are_skipped() -> None:
    quotes = _quotes()
    only_short = quotes.loc[quotes["dte_days"] == 4]
    assert score_latest_session(only_short, CalibrationMap.identity(0)).empty
    no_close = quotes.loc[quotes["underlying"] == "AAPL"].assign(underlying_close=np.nan)
    empty = score_latest_session(no_close, CalibrationMap.identity(0))
    assert empty.empty
    assert tuple(empty.columns) == SPREAD_COLUMNS


def test_chain_without_enough_usable_puts_is_skipped() -> None:
    quotes = lognormal_quotes(
        "SPY", date(2024, 1, 5), date(2024, 2, 2), 100.0, 0.25, RATE, [99.0, 100.0, 101.0]
    )
    assert score_latest_session(quotes, CalibrationMap.identity(0)).empty


def test_missing_column_raises() -> None:
    with pytest.raises(ValueError, match="quotes is missing"):
        score_latest_session(_quotes().drop(columns=["ask"]), CalibrationMap.identity(0))
    with pytest.raises(ValueError, match="quotes is missing"):
        latest_session(_quotes().drop(columns=["dte_days"]), min_dte_days=7)
