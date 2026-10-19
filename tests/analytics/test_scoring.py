from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

import oap.analytics.scoring as scoring_module
from oap.analytics.config import DEFAULT_CONFIG, PRODUCTION_MAP_ID, AnalyticsConfig
from oap.analytics.sample import chain_cdf
from oap.analytics.scoring import ENTRY_RULE, SPREAD_COLUMNS, score_latest_session
from oap.engine.calibration import CalibrationMap
from oap.engine.implied_distribution import QualityFlag, RiskNeutralCdf
from oap.engine.spread_scoring import PutCreditSpread, score_spread
from tests.analytics.frames import lognormal_quotes

RATE = DEFAULT_CONFIG.risk_free_apy
SPY_STRIKES = np.arange(80.0, 121.0, 1.0)
AAPL_STRIKES = np.arange(160.0, 221.0, 2.0)


def _quotes() -> pd.DataFrame:
    """One session (2024-01-05) of two underlyings, as ``read_latest_quotes`` returns it.

    SPY has a 4-day expiry that scoring must skip. Choosing the session is the job of
    ``LATEST_QUOTES_SQL`` (``tests/analytics/test_io.py``), not of scoring.
    """
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
                "AAPL", date(2024, 1, 5), date(2024, 2, 2), 190.0, 0.3, RATE, AAPL_STRIKES
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
    return score_latest_session(_quotes(), cmap or CalibrationMap.identity(0), config)


def test_short_dte_expiries_are_not_scored() -> None:
    scores = _scores()

    assert (scores["dte_days"] >= DEFAULT_CONFIG.min_dte_days).all()
    assert pd.Timestamp("2024-01-09") not in set(scores["expiration"])


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
    assert scores["dte_days"].isin([28, 42]).all()


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
    quotes = _quotes()
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
        assert row["fair_credit"] == pytest.approx(direct.fair_credit, abs=1e-12)
        assert row["fair_credit_raw"] == pytest.approx(plain.fair_credit, abs=1e-12)
        assert row["edge"] == pytest.approx(direct.expected_payoff, abs=1e-12)
        assert row["edge"] == row["expected_payoff"]
        assert row["edge_raw"] == pytest.approx(plain.expected_payoff, abs=1e-12)
        assert row["edge_natural"] == pytest.approx(
            row["credit_natural"] - direct.fair_credit, abs=1e-12
        )
        assert row["edge_pct"] == pytest.approx(direct.edge_pct, abs=1e-12)
        assert row["edge_pop"] == pytest.approx(direct.prob_profit - plain.prob_profit, abs=1e-12)
        assert row["pop_implied"] == pytest.approx(spread.pop_implied, abs=1e-12)
        assert row["pop_gap"] == pytest.approx(direct.prob_profit - spread.pop_implied, abs=1e-12)
        assert row["pop_gap_raw"] == pytest.approx(
            plain.prob_profit - spread.pop_implied, abs=1e-12
        )
        assert row["payoff_std"] == pytest.approx(direct.payoff_std, abs=1e-12)
        assert row["reward_to_risk"] == pytest.approx(direct.reward_to_risk, abs=1e-12)


def test_natural_credit_is_short_bid_minus_long_ask() -> None:
    scores = _scores()
    quotes = _quotes()
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
    scores = score_latest_session(_quotes(), _tilt(), map_id="fold_2024")
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


def test_identity_map_has_no_probability_edge_and_equal_fair_credits() -> None:
    scores = _scores()
    np.testing.assert_allclose(scores["edge_pop"], 0.0, atol=1e-12)
    np.testing.assert_allclose(scores["fair_credit"], scores["fair_credit_raw"], atol=1e-12)
    np.testing.assert_allclose(scores["edge"], scores["edge_raw"], atol=1e-12)


def test_edge_columns_are_consistent() -> None:
    scores = _scores(_tilt())
    assert (scores["edge"] == scores["expected_payoff"]).all()
    np.testing.assert_allclose(
        scores["fair_credit"] + scores["edge"], scores["credit"], atol=1e-9, rtol=0
    )
    np.testing.assert_allclose(scores["edge_pct"], scores["edge"] / scores["credit"])
    assert (scores["edge_pct"] <= 1.0).all()
    assert scores["fair_credit"].between(0.0, 1e9).all()
    assert (scores["fair_credit"] <= scores["width"] + 1e-9).all()
    assert (scores["payoff_std"] <= scores["width"] / 2 + 1e-9).all()
    assert (scores["edge_pop"] != 0).any()


def _flagged(monkeypatch: pytest.MonkeyPatch, flag: QualityFlag, underlying: str) -> None:
    """Make ``chain_cdf`` add ``flag`` to the CDF of one underlying."""
    original = chain_cdf

    def with_flag(chain: pd.DataFrame, *, years: float, rate: float) -> RiskNeutralCdf | None:
        cdf = original(chain, years=years, rate=rate)
        if cdf is None or str(chain["underlying"].iloc[0]) != underlying:
            return cdf
        return replace(cdf, flags=cdf.flags | {flag})

    monkeypatch.setattr(scoring_module, "chain_cdf", with_flag)


def _guarded(scores: pd.DataFrame, config: AnalyticsConfig) -> pd.Series:
    return (
        scores["eligible"]
        & (scores["credit"] >= config.min_edge_credit)
        & (scores["credit_natural"] >= config.min_natural_fraction * scores["credit"])
    )


_TAIL = "left_tail_uncovered|right_tail_uncovered|sparse|forward_unknown"

GUARD_CONFIGS = [
    DEFAULT_CONFIG,
    AnalyticsConfig(min_edge_credit=2.0),
    AnalyticsConfig(min_natural_fraction=0.95),
    AnalyticsConfig(min_edge_credit=0.0, min_natural_fraction=0.0, entry_min_pop=0.9),
]


@pytest.mark.parametrize("config", GUARD_CONFIGS)
def test_alternative_ranks_cover_exactly_the_guarded_candidates(config: AnalyticsConfig) -> None:
    scores = _scores(_tilt(), config)
    guarded = _guarded(scores, config)
    assert guarded.any()
    for column in ("rank_edge", "rank_rr"):
        assert scores[column].dtype == "Int64"
        assert scores[column].notna().tolist() == guarded.tolist()
        ranked = scores.loc[guarded].sort_values(column)
        assert ranked[column].tolist() == list(range(1, len(ranked) + 1))
    assert scores["rank_edge"].notna().tolist() == scores["rank_rr"].notna().tolist()
    assert scores.loc[scores["rank"].isna(), ["rank_edge", "rank_rr"]].isna().all().all()


def test_alternative_ranks_follow_the_rank_spreads_orders() -> None:
    scores = _scores(_tilt())
    for column, primary in (("rank_edge", "edge_pct"), ("rank_rr", "reward_to_risk")):
        ranked = scores.loc[scores[column].notna()].sort_values(column)
        assert len(ranked) > 10
        keys = list(
            zip(
                -ranked[primary],
                -ranked["prob_profit"],
                -ranked["short_strike"],
                ranked["long_strike"],
                strict=True,
            )
        )
        assert keys == sorted(keys)


def test_each_guard_blocks_the_alternative_ranks() -> None:
    config = AnalyticsConfig(min_edge_credit=1.0, min_natural_fraction=0.9)
    scores = _scores(_tilt(), config)
    reasons = {
        "ineligible": ~scores["eligible"],
        "credit floor": scores["credit"] < config.min_edge_credit,
        "natural fraction": scores["credit_natural"]
        < config.min_natural_fraction * scores["credit"],
    }
    for name, mask in reasons.items():
        assert mask.any(), name
        assert scores.loc[mask, ["rank_edge", "rank_rr"]].isna().all().all(), name


def _entry_candidates(scores: pd.DataFrame, config: AnalyticsConfig) -> pd.Series:
    return (
        _guarded(scores, config)
        & (scores["prob_profit"] >= config.entry_min_pop)
        & (scores["edge_natural"] > 0)
        & ~scores["extrapolated"]
        & ~scores["flags"].str.contains(_TAIL)
    )


@pytest.mark.parametrize("config", GUARD_CONFIGS)
def test_entry_rank_covers_exactly_the_candidates_and_is_contiguous(
    config: AnalyticsConfig,
) -> None:
    scores = _scores(_tilt(), config)
    expected = _entry_candidates(scores, config)
    assert expected.any()
    assert scores["rank_entry"].dtype == "Int64"
    assert scores["rank_entry"].notna().tolist() == expected.tolist()
    ranked = scores.loc[expected].sort_values("rank_entry")
    assert ranked["rank_entry"].tolist() == list(range(1, len(ranked) + 1))


def test_entry_rank_is_ordered_by_return_then_reward_to_risk() -> None:
    scores = _scores(_tilt())
    ranked = scores.loc[scores["rank_entry"].notna()].sort_values("rank_entry")
    assert len(ranked) > 10
    keys = list(
        zip(
            -ranked["annualised_roc"],
            -ranked["reward_to_risk"],
            -ranked["prob_profit"],
            -ranked["short_strike"],
            ranked["long_strike"],
            strict=True,
        )
    )
    assert keys == sorted(keys)


def test_each_entry_guard_nulls_the_entry_rank() -> None:
    scores = _scores(_tilt())
    config = DEFAULT_CONFIG
    reasons = {
        "ineligible": ~scores["eligible"],
        "credit floor": scores["credit"] < config.min_edge_credit,
        "low probability": scores["prob_profit"] < config.entry_min_pop,
        "negative natural edge": scores["edge_natural"] <= 0,
    }
    for name, mask in reasons.items():
        assert mask.any(), name
        assert scores.loc[mask, "rank_entry"].isna().all(), name
    strict = AnalyticsConfig(entry_min_pop=0.9)
    strict_scores = _scores(_tilt(), strict)
    only_pop = _guarded(strict_scores, strict) & (strict_scores["prob_profit"] < 0.9)
    assert only_pop.any()
    assert strict_scores.loc[only_pop, "rank_entry"].isna().all()
    assert strict_scores.loc[only_pop, "rank_edge"].notna().all()
    raw = _scores()  # the identity map leaves almost no edge, so the natural edge is negative
    only_edge = _guarded(raw, config) & (raw["edge_natural"] <= 0)
    assert only_edge.any()
    assert raw.loc[only_edge, "rank_entry"].isna().all()
    assert raw.loc[only_edge, "rank_edge"].notna().all()


@pytest.mark.parametrize("flag", [QualityFlag.LEFT_TAIL_UNCOVERED, QualityFlag.SPARSE])
def test_tail_flags_null_the_entry_rank_but_not_the_other_ranks(
    monkeypatch: pytest.MonkeyPatch, flag: QualityFlag
) -> None:
    _flagged(monkeypatch, flag, "AAPL")
    scores = _scores(_tilt())
    flagged = scores["underlying"] == "AAPL"
    assert scores.loc[flagged, "flags"].str.contains(flag.value).all()
    assert scores.loc[flagged, "rank_entry"].isna().all()
    assert scores.loc[flagged, "rank_edge"].notna().any()
    assert scores.loc[~flagged, "rank_entry"].notna().any()
    assert (
        scores["rank_entry"].notna().tolist() == _entry_candidates(scores, DEFAULT_CONFIG).tolist()
    )


def test_entry_rule_states_the_configured_thresholds() -> None:
    assert "65%" in ENTRY_RULE
    assert "$0.25" in ENTRY_RULE
    assert "50% of mid" in ENTRY_RULE
    assert ENTRY_RULE.endswith("then reward/risk.")


def test_probability_gap_columns() -> None:
    scores = _scores(_tilt())
    np.testing.assert_allclose(scores["pop_implied"], scores["max_loss"] / scores["width"])
    np.testing.assert_allclose(scores["pop_implied"], 1.0 - scores["credit"] / scores["width"])
    assert scores["pop_implied"].between(0.0, 1.0).all()
    np.testing.assert_allclose(scores["pop_gap"], scores["prob_profit"] - scores["pop_implied"])
    np.testing.assert_allclose(
        scores["pop_gap_raw"], scores["prob_profit_raw"] - scores["pop_implied"]
    )
    assert scores["pop_gap"].abs().le(1.0).all()
    # Calibration moves the gap by exactly edge_pop.
    np.testing.assert_allclose(
        scores["pop_gap"] - scores["pop_gap_raw"], scores["edge_pop"], atol=1e-12
    )
    # The raw gap is the control: small because only partial losses and interest separate them.
    assert scores["pop_gap_raw"].abs().max() < 0.15
