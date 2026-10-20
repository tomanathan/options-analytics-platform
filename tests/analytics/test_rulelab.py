import math
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.ranking import annualise, kelly_growth, rank_score
from oap.analytics.rulelab import (
    BASELINE_RULE,
    IV_RANK_WINDOW,
    LAB_METRICS,
    PREVIOUS_RULE,
    REGIME_COLUMNS,
    Rule,
    apply_rule,
    atm_iv,
    describe_rule,
    evaluate,
    flatten,
    iv_features,
    live_rule,
    pick_rules,
    prepare,
    regime_features,
    return_features,
    rule_fields,
    rule_grid,
)
from oap.analytics.scoring import ENTRY_RULE
from oap.analytics.strategy import ELIGIBLE_ALL, SETTLED_COLUMNS, backtest_session, settle_trades
from oap.engine.calibration import CalibrationMap
from tests.analytics.frames import lognormal_quotes, outcomes_frame

GRID = rule_grid()
YEARS_DEV = range(2021, 2025)
YEARS_HOLDOUT = range(2025, 2027)


def _row(n: int, **values: object) -> dict[str, object]:
    """A guarded, settled trade on SPY with neutral defaults; ``values`` override."""
    row: dict[str, object] = dict.fromkeys(SETTLED_COLUMNS, 0.0)
    trade_date = pd.Timestamp(str(values.pop("day", "2024-03-01")))
    row.update(
        {
            "spread_key": f"k{n}",
            "underlying": "SPY",
            "trade_date": trade_date,
            "expiration": trade_date + pd.Timedelta(days=28),
            "dte_days": 28,
            "years": 28 / 365,
            "underlying_close": 100.0,
            "short_strike": 92.0,
            "long_strike": 87.0,
            "width": 5.0,
            "credit": 1.2,
            "credit_natural": 1.0,
            "fair_credit": 0.8,
            "edge_natural": 0.2,
            "short_moneyness": 0.92,
            "prob_profit": 0.8,
            "pop_implied": 0.76,
            "annualised_roc": 0.5,
            "reward_to_risk": 0.1,
            "kelly_fraction": 0.2,
            "expected_roc": 0.04,
            "flags": "",
            "eligible": True,
            "extrapolated": False,
            "rank_entry": n,
            "map_id": f"fold_{trade_date.year}",
            "strategy": ELIGIBLE_ALL,
            "is_out_of_sample": True,
            "settlement_date": trade_date + pd.Timedelta(days=28),
            "settlement_close": 101.0,
            "max_loss_natural": 4.0,
            "realised_payoff": 1.0,
            "realised_return": 0.25,
            "win": True,
            "max_loss_hit": False,
        }
    )
    row.update(values)
    return row


def _frame(rows: Sequence[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    frame["rank_entry"] = frame["rank_entry"].astype("Int64")
    return frame


def _regime(rows: Sequence[tuple[str, str, float, float, float]] = ()) -> pd.DataFrame:
    """Regime rows of (underlying, day, ret_20, atm_iv_change_5, iv_rank_120)."""
    frame = pd.DataFrame(
        [
            {
                "underlying": u,
                "trade_date": pd.Timestamp(d),
                "ret_5": 0.0,
                "ret_20": r20,
                "atm_iv": 0.3,
                "atm_iv_change_5": change,
                "iv_rank_120": rank,
            }
            for u, d, r20, change, rank in rows
        ],
        columns=list(REGIME_COLUMNS),
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def _keys(selected: pd.DataFrame) -> list[str]:
    return [str(k) for k in selected["spread_key"]]


# --- rules -----------------------------------------------------------------------------------


def test_rule_ids_are_stable_short_and_unique() -> None:
    assert BASELINE_RULE.rule_id == "ps-d45_70-m95_100-all-any-e0-n10"
    assert PREVIOUS_RULE.rule_id == "rm-dany-many-all-any-e0-n10"
    rule = Rule(
        rank_by="return_natural",
        dte_band=(21, 45),
        moneyness_band=(0.90, 0.95),
        one_per_underlying_expiry=True,
        regime="calm",
        natural_edge_margin=0.10,
    )
    assert rule.rule_id == "rn-d21_45-m90_95-one-calm-e10-n10"
    assert Rule(**{**rule.__dict__}).rule_id == rule.rule_id
    assert len(GRID) == 1600
    assert GRID[:2] == (BASELINE_RULE, PREVIOUS_RULE)
    assert len({r.rule_id for r in GRID}) == 1600
    assert {r.top_n for r in rule_grid(top_n=5)} == {5}
    assert rule_grid(top_n=5)[0] == Rule(**{**BASELINE_RULE.__dict__, "top_n": 5})
    assert max(len(r.rule_id) for r in GRID) <= 40


def test_rules_reject_invalid_fields_and_describe_themselves() -> None:
    with pytest.raises(ValueError, match="top_n"):
        Rule(top_n=0)
    with pytest.raises(ValueError, match="band"):
        Rule(dte_band=(21, 7))
    with pytest.raises(ValueError, match="margin"):
        Rule(natural_edge_margin=-0.1)
    with pytest.raises(ValueError, match="rank_by"):
        Rule(rank_by="nope")  # type: ignore[arg-type]
    text = describe_rule(
        Rule(rank_by="kelly_growth", dte_band=(21, 45), regime="trend_up", top_n=5)
    )
    assert text.startswith("Rank by expected log growth")
    assert "21 to 44 days to expiry" in text
    assert "20-session return is positive" in text
    assert text.endswith("top 5 per session, after every entry guard.")
    assert rule_fields(Rule(moneyness_band=(0.9, 0.95)))["moneyness_band"] == "0.90-0.95"


def test_the_baseline_is_the_live_rule_of_the_config_in_the_same_words() -> None:
    assert live_rule() == BASELINE_RULE
    assert live_rule(top_n=3).top_n == 3
    words = describe_rule(BASELINE_RULE)
    assert "45 to 69 days to expiry" in words
    assert "45 to 69 days to expiry" in ENTRY_RULE
    assert "95% to below 100% of the close" in words
    assert "95% to below 100% of the close" in ENTRY_RULE
    shrunk = "annualised natural return with the POP shrunk halfway toward the market-implied POP"
    assert shrunk in words
    assert shrunk in ENTRY_RULE


# --- rankings --------------------------------------------------------------------------------


def test_kelly_growth_matches_a_hand_case_and_caps_the_fraction() -> None:
    got = kelly_growth(np.array([0.8, 0.8]), np.array([0.25, 0.25]), np.array([0.3, 0.9]))
    assert got[0] == pytest.approx(0.8 * math.log(1.075) + 0.2 * math.log(0.7))
    assert got[1] == pytest.approx(0.8 * math.log(1.125) + 0.2 * math.log(0.5))
    assert kelly_growth(np.array([0.9]), np.array([1.0]), np.array([0.0]))[0] == 0.0


@given(
    p=st.floats(0.0, 1.0),
    b=st.floats(0.01, 20.0),
    f=st.floats(0.0, 1.0),
)
def test_kelly_growth_is_not_positive_without_an_edge(p: float, b: float, f: float) -> None:
    if not p * b < 1.0 - p:
        return
    assert kelly_growth(np.array([p]), np.array([b]), np.array([f]))[0] <= 1e-12


def test_natural_and_shrunk_returns_on_a_hand_row() -> None:
    frame = _frame([_row(1)])
    years = np.array([28 / 365])
    # natural: edge 0.2 over natural max loss 4.0.
    assert rank_score(frame, "return_natural")[0] == pytest.approx(
        annualise(np.array([0.05]), years)[0]
    )
    # shrunk POP: 0.5 * 0.8 + 0.5 * 0.76 = 0.78; odds 1 / 4.
    q = 0.78
    assert rank_score(frame, "pop_shrunk_return")[0] == pytest.approx(
        annualise(np.array([q * 0.25 - (1 - q)]), years)[0]
    )
    assert rank_score(frame, "return_mid")[0] == 0.5
    assert rank_score(frame, "reward_to_risk")[0] == 0.1
    assert annualise(np.array([-1.0, -2.0]), np.array([0.1, 0.1])).tolist() == [-1.0, -1.0]


# --- gates -----------------------------------------------------------------------------------


def test_each_gate_keeps_only_matching_rows() -> None:
    rows = [
        _row(1, dte_days=10, short_moneyness=0.85),
        _row(2, dte_days=30, short_moneyness=0.93),
        _row(3, dte_days=50, short_moneyness=0.97, credit_natural=0.85),
        _row(4, dte_days=21, short_moneyness=0.90, underlying="AAPL"),
        _row(5, eligible=False),
        _row(6, prob_profit=0.6),
        _row(7, edge_natural=0.0),
        _row(8, flags="sparse"),
        _row(9, credit_natural=0.5),
        _row(10, extrapolated=True),
    ]
    frame = _frame(rows)
    regime = _regime(
        [
            ("SPY", "2024-03-01", 0.05, 0.30, 0.2),
            ("AAPL", "2024-03-01", -0.02, 0.10, 0.7),
        ]
    )

    def keys(**fields: object) -> list[str]:
        return sorted(_keys(apply_rule(frame, regime, Rule(**fields))))  # type: ignore[arg-type]

    assert keys() == ["k1", "k2", "k3", "k4"]  # k5 to k10 each fail an entry guard
    assert keys(dte_band=(7, 21)) == ["k1"]
    assert keys(dte_band=(21, 45)) == ["k2", "k4"]
    assert keys(dte_band=(45, 70)) == ["k3"]
    assert keys(moneyness_band=(0.80, 0.90)) == ["k1"]
    assert keys(moneyness_band=(0.90, 0.95)) == ["k2", "k4"]
    assert keys(moneyness_band=(0.95, 1.00)) == ["k3"]
    assert keys(regime="trend_up") == ["k1", "k2", "k3"]
    assert keys(regime="calm") == ["k4"]
    assert keys(regime="trend_up_calm") == []
    assert keys(regime="high_iv_rank") == ["k4"]
    # 0.85 natural against 0.8 fair passes a 0% margin but not 10%.
    assert keys(natural_edge_margin=0.10) == ["k1", "k2", "k4"]
    assert keys(top_n=2) == ["k1", "k2"]


def test_a_missing_regime_feature_fails_the_regime_gate() -> None:
    frame = _frame([_row(1), _row(2, underlying="AAPL")])
    regime = _regime([("SPY", "2024-03-01", 0.05, math.nan, math.nan)])
    assert _keys(apply_rule(frame, regime, Rule(regime="trend_up"))) == ["k1"]
    assert _keys(apply_rule(frame, regime, Rule(regime="calm"))) == []
    assert _keys(apply_rule(frame, regime, Rule())) == ["k1", "k2"]


def test_one_per_underlying_expiry_keeps_the_best_ranked() -> None:
    later = pd.Timestamp("2024-03-01") + pd.Timedelta(days=42)
    frame = _frame(
        [
            _row(1, annualised_roc=0.3),
            _row(2, annualised_roc=0.9),
            _row(3, annualised_roc=0.6, expiration=later),
            _row(4, annualised_roc=0.5, underlying="AAPL"),
            _row(5, annualised_roc=0.7, day="2024-03-04"),
        ]
    )
    rule = Rule(one_per_underlying_expiry=True)
    assert _keys(apply_rule(frame, _regime(), rule)) == ["k2", "k3", "k4", "k5"]
    assert _keys(apply_rule(frame, _regime(), Rule(top_n=2))) == ["k2", "k3", "k5"]


def test_ties_break_by_the_live_tiebreak_not_by_rank_entry() -> None:
    # Both have no Kelly growth; the higher annualised return wins the tie whatever rank_entry says.
    frame = _frame(
        [
            _row(1, kelly_fraction=0.0, annualised_roc=0.3),
            _row(2, kelly_fraction=0.0, annualised_roc=0.6, rank_entry=None),
        ]
    )
    assert _keys(apply_rule(frame, _regime(), Rule(rank_by="kelly_growth"))) == ["k2", "k1"]


def _guarded(row: pd.Series) -> bool:
    """The entry guard of one row, written out per row as a reference."""
    blocking = {"left_tail_uncovered", "right_tail_uncovered", "sparse", "forward_unknown"}
    return bool(
        row["eligible"]
        and row["credit"] >= DEFAULT_CONFIG.min_edge_credit
        and row["credit_natural"] >= DEFAULT_CONFIG.min_natural_fraction * row["credit"]
        and row["prob_profit"] >= DEFAULT_CONFIG.entry_min_pop
        and row["edge_natural"] > 0
        and not row["extrapolated"]
        and not blocking & set(str(row["flags"]).split(","))
    )


def _tie_key(row: pd.Series) -> tuple[float, ...]:
    """The live tie-break of one row, smallest first."""
    rr = float(row["reward_to_risk"])
    return (
        -float(row["annualised_roc"]),
        float(math.isnan(rr)),
        0.0 if math.isnan(rr) else -rr,
        -float(row["prob_profit"]),
        -float(row["short_strike"]),
        float(row["long_strike"]),
    )


def _slow_select(frame: pd.DataFrame, regime: pd.DataFrame, rule: Rule) -> list[str]:
    """A per-row reference implementation of ``apply_rule``."""
    features = {
        (str(r["underlying"]), pd.Timestamp(r["trade_date"])): r for _, r in regime.iterrows()
    }
    chosen: list[str] = []
    for _, session in frame.groupby("trade_date", sort=True):
        candidates = []
        for i, (_, row) in enumerate(session.iterrows()):
            if not _guarded(row):
                continue
            if rule.dte_band and not rule.dte_band[0] <= row["dte_days"] < rule.dte_band[1]:
                continue
            band = rule.moneyness_band
            if band and not band[0] <= row["short_moneyness"] < band[1]:
                continue
            f = features.get((str(row["underlying"]), pd.Timestamp(row["trade_date"])))
            r20 = math.nan if f is None else float(f["ret_20"])
            change = math.nan if f is None else float(f["atm_iv_change_5"])
            ivr = math.nan if f is None else float(f["iv_rank_120"])
            if rule.regime in ("trend_up", "trend_up_calm") and not r20 > 0:
                continue
            if rule.regime in ("calm", "trend_up_calm") and not change < 0.2:
                continue
            if rule.regime == "high_iv_rank" and not ivr >= 0.5:
                continue
            if not row["credit_natural"] >= (1 + rule.natural_edge_margin) * row["fair_credit"]:
                continue
            score = float(rank_score(session.iloc[[i]], rule.rank_by)[0])
            score = -math.inf if math.isnan(score) else score
            candidates.append((-score, _tie_key(row), row))
        candidates.sort(key=lambda c: (c[0], c[1]))
        seen: set[tuple[str, pd.Timestamp]] = set()
        picked = 0
        for _, _, row in candidates:
            key = (str(row["underlying"]), pd.Timestamp(row["expiration"]))
            if rule.one_per_underlying_expiry and key in seen:
                continue
            seen.add(key)
            if picked < rule.top_n:
                chosen.append(str(row["spread_key"]))
                picked += 1
    return chosen


def _random_trades(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(1, 40))
    days = pd.to_datetime(["2024-03-01", "2024-03-04", "2025-02-03"])
    rows = []
    for i in range(n):
        day = days[int(rng.integers(0, len(days)))]
        dte = int(rng.integers(7, 80))
        width = float(rng.choice([1.0, 2.5, 5.0]))
        natural = float(rng.uniform(0.05, 0.6)) * width
        fair = natural * float(rng.uniform(0.7, 1.2))
        rows.append(
            _row(
                i,
                day=str(day.date()),
                underlying=str(rng.choice(["SPY", "AAPL"])),
                expiration=day + pd.Timedelta(days=int(rng.choice([14, 28]))),
                dte_days=dte,
                years=dte / 365,
                width=width,
                credit_natural=natural,
                fair_credit=fair,
                edge_natural=natural - fair,
                short_moneyness=float(rng.uniform(0.78, 1.0)),
                prob_profit=float(rng.uniform(0.6, 0.95)),
                pop_implied=float(rng.uniform(0.5, 0.9)),
                kelly_fraction=float(rng.choice([0.0, rng.uniform(0, 1)])),
                annualised_roc=float(rng.choice([0.4, rng.normal(0.3, 0.5)])),
                reward_to_risk=float(rng.choice([math.nan, rng.normal()])),
                eligible=bool(rng.uniform() >= 0.15),
                flags=str(rng.choice(["", "", "", "sparse", "clipped"])),
                short_strike=float(rng.choice([90.0, 92.0, 95.0])),
                rank_entry=None,
            )
        )
    frame = _frame(rows)
    regime_rows = []
    for underlying in ("SPY", "AAPL"):
        for day in days[:2]:
            regime_rows.append(
                (
                    underlying,
                    str(day.date()),
                    float(rng.choice([math.nan, rng.normal()])),
                    float(rng.normal(0.1, 0.2)),
                    float(rng.uniform()),
                )
            )
    return frame, _regime(regime_rows)


@settings(max_examples=60, deadline=None)
@given(seed=st.integers(0, 2**32 - 1), rule=st.sampled_from(GRID), top_n=st.integers(1, 4))
def test_vectorised_selection_equals_a_per_row_reference(seed: int, rule: Rule, top_n: int) -> None:
    frame, regime = _random_trades(seed)
    rule = Rule(**{**rule.__dict__, "top_n": top_n})
    assert _keys(apply_rule(frame, regime, rule)) == _slow_select(frame, regime, rule)


# --- baseline equals the live rule -----------------------------------------------------------


def test_the_baseline_rule_selects_the_live_entry_top10() -> None:
    day = date(2024, 1, 5)
    rate = DEFAULT_CONFIG.risk_free_apy
    quotes = pd.concat(
        [
            lognormal_quotes(
                "SPY", day, day + timedelta(days=d), 100.0, 0.25, rate, np.arange(80.0, 121.0)
            )
            for d in (14, 28, 49, 63)
        ]
        + [
            lognormal_quotes(
                "AAPL", day, day + timedelta(days=56), 190.0, 0.3, rate, np.arange(160.0, 221.0, 2)
            )
        ],
        ignore_index=True,
    )
    snapshots = quotes[["underlying", "trade_date", "expiration"]].drop_duplicates()
    cmap = CalibrationMap(
        np.array([0.0, 0.2, 0.5, 0.8, 1.0]),
        np.array([0.0, 0.1, 0.3, 0.7, 1.0]),
        n_samples=500,
        is_identity=False,
    )
    trades = backtest_session(quotes, snapshots.assign(status="ok"), {"fold_2024": cmap}, top_n=10)
    keys = trades[["underlying", "expiration"]].drop_duplicates()
    outcomes = outcomes_frame(
        [
            (u, e.date(), e.date(), 95.0)
            for u, e in zip(keys["underlying"], keys["expiration"], strict=True)
        ]
    )
    settled, _ = settle_trades(trades, outcomes)
    everything = settled.loc[settled["strategy"] == ELIGIBLE_ALL]
    live = settled.loc[settled["strategy"] == "entry_top10", "spread_key"].tolist()
    assert len(live) == 10
    assert _keys(apply_rule(everything, _regime(), BASELINE_RULE)) == live


# --- regime features -------------------------------------------------------------------------


def _daily(underlying: str, log_returns: Sequence[float]) -> pd.DataFrame:
    days = pd.bdate_range("2024-01-01", periods=len(log_returns))
    return pd.DataFrame(
        {"underlying": underlying, "trade_date": days, "log_return": list(log_returns)}
    )


def test_return_features_sum_the_last_sessions_and_ignore_split_days() -> None:
    returns = [math.nan] + [0.01] * 30
    returns[25] = -2.3  # a 10:1 split as traded
    daily = pd.concat([_daily("NVDA", returns), _daily("SPY", [0.002] * 25)], ignore_index=True)
    out = return_features(daily)
    nvda = out.loc[out["underlying"] == "NVDA"].reset_index(drop=True)
    assert nvda["ret_20"].iloc[:20].isna().all()
    assert nvda["ret_20"].iloc[20] == pytest.approx(0.20)
    assert nvda["ret_5"].iloc[10] == pytest.approx(0.05)
    assert nvda["ret_20"].iloc[30] == pytest.approx(0.19)  # the split day counts as 0
    spy = out.loc[out["underlying"] == "SPY"].reset_index(drop=True)
    assert spy["ret_20"].iloc[19] == pytest.approx(0.04)


def test_atm_iv_uses_the_nearest_otm_quote_of_the_shortest_usable_expiry() -> None:
    day = pd.Timestamp("2024-03-01")

    def quote(dte: int, strike: float, right: str, iv: float) -> dict[str, object]:
        return {
            "underlying": "SPY",
            "trade_date": day,
            "expiration": day + pd.Timedelta(days=dte),
            "strike": strike,
            "option_right": right,
            "source_iv": iv,
            "underlying_close": 100.0,
            "dte_days": dte,
        }

    quotes = pd.DataFrame(
        [
            quote(3, 100.0, "P", 0.90),  # too short
            quote(10, 99.0, "P", 0.21),
            quote(10, 101.0, "C", 0.19),
            quote(10, 99.5, "C", 0.50),  # in the money
            quote(10, 100.5, "P", 0.50),  # in the money
            quote(10, 98.0, "P", 0.30),
            quote(10, 100.0, "C", math.nan),  # no IV
            quote(30, 100.0, "P", 0.40),  # longer expiry
        ]
    )
    out = atm_iv(quotes)
    assert len(out) == 1
    assert out["atm_iv"].iloc[0] == pytest.approx(0.20)
    assert atm_iv(quotes.iloc[[0]]).empty


def test_iv_features_change_and_rank_on_known_series() -> None:
    n = IV_RANK_WINDOW + 10
    days = pd.bdate_range("2024-01-01", periods=n)
    rising = pd.DataFrame(
        {"underlying": "UP", "trade_date": days, "atm_iv": np.linspace(0.2, 0.5, n)}
    )
    falling = pd.DataFrame(
        {"underlying": "DOWN", "trade_date": days, "atm_iv": np.linspace(0.5, 0.2, n)}
    )
    out = iv_features(pd.concat([rising, falling], ignore_index=True))
    up = out.loc[out["underlying"] == "UP"].reset_index(drop=True)
    down = out.loc[out["underlying"] == "DOWN"].reset_index(drop=True)
    assert up["iv_rank_120"].iloc[: IV_RANK_WINDOW - 1].isna().all()
    assert up["iv_rank_120"].iloc[IV_RANK_WINDOW - 1 :].eq(1.0).all()
    assert down["iv_rank_120"].iloc[IV_RANK_WINDOW - 1 :].eq(0.0).all()
    assert up["atm_iv_change_5"].iloc[:5].isna().all()
    expected = up["atm_iv"].iloc[10] / up["atm_iv"].iloc[5] - 1
    assert up["atm_iv_change_5"].iloc[10] == pytest.approx(expected)
    ladder = pd.DataFrame(
        {
            "underlying": "L",
            "trade_date": days[:IV_RANK_WINDOW],
            "atm_iv": [*np.arange(IV_RANK_WINDOW - 1) / 1000 + 0.2, 0.2 + 59.5 / 1000],
        }
    )
    assert iv_features(ladder)["iv_rank_120"].iloc[-1] == pytest.approx(60 / 119)


def test_regime_features_join_both_sides() -> None:
    daily = _daily("SPY", [math.nan] + [0.01] * 24)
    atm = pd.DataFrame(
        {
            "underlying": ["SPY", "QQQ"],
            "trade_date": pd.to_datetime(["2024-01-29", "2024-01-29"]),
            "atm_iv": [0.2, 0.3],
        }
    )
    out = regime_features(daily, atm)
    assert list(out.columns) == list(REGIME_COLUMNS)
    spy = out.loc[(out["underlying"] == "SPY") & (out["trade_date"] == "2024-01-29")]
    assert spy["ret_20"].iloc[0] == pytest.approx(0.20)
    assert spy["atm_iv"].iloc[0] == 0.2
    qqq = out.loc[out["underlying"] == "QQQ"]
    assert qqq["ret_20"].isna().all()


# --- evaluation ------------------------------------------------------------------------------


def _settled(
    n: int, day: str, payoff: float, *, underlying: str = "SPY", **values: object
) -> dict[str, object]:
    return _row(
        n,
        day=day,
        underlying=underlying,
        realised_payoff=payoff,
        realised_return=payoff / 4.0,
        win=payoff > 0,
        max_loss_hit=payoff <= -4.0,
        **values,
    )


def test_evaluate_on_a_hand_trade_set() -> None:
    frame = _frame(
        [
            _settled(1, "2023-01-03", 1.0),
            _settled(2, "2023-01-03", -4.0, underlying="AAPL"),
            _settled(3, "2023-02-01", 1.0),
            _settled(4, "2025-03-03", 1.0, prob_profit=0.7),
            _settled(5, "2025-03-04", -1.0),
            _settled(6, "2020-06-01", 1.0, is_out_of_sample=False),
        ]
    )
    metrics = evaluate(
        prepare(frame, _regime()), PREVIOUS_RULE, dev_years=YEARS_DEV, holdout_years=YEARS_HOLDOUT
    )
    dev, hold = metrics["dev"], metrics["holdout"]
    assert set(dev) == set(LAB_METRICS)
    assert dev["n_trades"] == 3
    assert dev["n_sessions"] == 2
    assert dev["win_rate"] == pytest.approx(2 / 3)
    assert dev["mean_predicted_pop"] == pytest.approx(0.8)
    returns = np.array([0.25, -1.0, 0.25])
    assert dev["mean_realised_return"] == pytest.approx(returns.mean())
    assert dev["total_return"] == pytest.approx(-2.0 / 12.0)
    assert dev["sharpe_per_trade"] == pytest.approx(returns.mean() / returns.std(ddof=1))
    # Sessions book -0.375 then +0.25: the drawdown is 0.375 from the starting peak of 0.
    assert dev["max_drawdown"] == pytest.approx(0.375)
    assert dev["max_loss_rate"] == pytest.approx(1 / 3)
    assert hold["n_trades"] == 2
    assert hold["mean_predicted_pop"] == pytest.approx(0.75)
    assert hold["mean_realised_return"] == pytest.approx(0.0)
    assert hold["max_drawdown"] == pytest.approx(0.25)
    assert hold["mean_realised_return_ci_low"] <= 0.0 <= hold["mean_realised_return_ci_high"]
    flat = flatten(metrics)
    assert flat["n_trades_dev"] == 3
    assert "mean_realised_return_ci_low_holdout" in flat


def test_a_trades_year_decides_its_period_and_periods_must_not_overlap() -> None:
    frame = _frame(
        [
            _settled(1, "2024-12-30", 1.0, expiration=pd.Timestamp("2025-01-17")),
            _settled(2, "2025-01-02", -1.0, expiration=pd.Timestamp("2025-01-17")),
        ]
    )
    prepared = prepare(frame, _regime())
    metrics = evaluate(prepared, PREVIOUS_RULE, dev_years=YEARS_DEV, holdout_years=YEARS_HOLDOUT)
    assert metrics["dev"]["n_trades"] == 1
    assert metrics["dev"]["mean_realised_return"] == pytest.approx(0.25)
    assert metrics["holdout"]["n_trades"] == 1
    assert metrics["holdout"]["mean_realised_return"] == pytest.approx(-0.25)
    empty = evaluate(prepared, PREVIOUS_RULE, dev_years=[2019], holdout_years=[2030])
    assert empty["dev"]["n_trades"] == 0
    assert math.isnan(empty["dev"]["sharpe_per_trade"])
    assert math.isnan(empty["holdout"]["mean_realised_return_ci_low"])
    with pytest.raises(ValueError, match="overlap"):
        evaluate(prepared, PREVIOUS_RULE, dev_years=[2024], holdout_years=[2024, 2025])


# --- choosing rules --------------------------------------------------------------------------


def _results(rows: Sequence[tuple[str, int, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "rule_id",
            "n_trades_dev",
            "max_drawdown_dev",
            "sharpe_per_trade_dev",
            "mean_realised_return_dev",
            "sharpe_per_trade_holdout",
        ],
    )


def test_pick_rules_uses_dev_metrics_only() -> None:
    results = _results(
        [
            ("base", 1000, 5.0, 0.00, 0.00, 0.00),
            ("a", 900, 8.0, 0.20, 0.05, -0.10),  # best dev Sharpe, high drawdown
            ("b", 800, 2.0, 0.10, 0.08, 0.05),  # best ROI under the median drawdown
            ("c", 700, 3.0, 0.05, 0.02, 0.02),
            ("d", 100, 1.0, 0.90, 0.50, 0.90),  # too few dev trades
            ("e", 0, math.nan, math.nan, math.nan, math.nan),
        ]
    )
    picks = pick_rules(results, baseline_id="base", min_dev_trades=400)
    assert picks.qualified["rule_id"].tolist() == ["a", "b", "c", "base"]
    assert picks.best_overall == "a"
    assert picks.drawdown_median == pytest.approx(3.0)
    assert picks.best_roi == "b"
    assert picks.beat_dev == 3
    assert picks.beat_both == 2
    assert picks.median_rule == "b"
    none = pick_rules(results, baseline_id="base", min_dev_trades=10_000)
    assert none.best_overall is None and none.best_roi is None and none.median_rule is None
    with pytest.raises(ValueError, match="baseline"):
        pick_rules(results, baseline_id="missing", min_dev_trades=1)
