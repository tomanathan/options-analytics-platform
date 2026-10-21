import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oap.analytics.growth import F_MAX
from oap.analytics.growth_rules import (
    DTE_BANDS,
    METRICS,
    MONEYNESS_BANDS,
    OPTION_COLUMNS,
    RANK_BYS,
    REGIME_GATES,
    GrowthRule,
    beat_counts,
    describe_rule,
    evaluate,
    evaluate_positions,
    flatten,
    holdout_line,
    line_metrics,
    pick_rules,
    prepare,
    random_positions,
    rule_fields,
    rule_grid,
    select_positions,
    session_weights,
)
from oap.analytics.rulelab import CALM_MAX_IV_CHANGE

DEV = (2021,)
HOLD = (2022,)


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Scored options with neutral defaults; each row's keys override."""
    base: dict[str, object] = {
        "underlying": "SPY",
        "trade_date": pd.Timestamp("2021-03-01"),
        "expiration": pd.Timestamp("2021-03-29"),
        "dte_days": 28,
        "right": "call",
        "strike": 100.0,
        "moneyness": 1.0,
        "is_out_of_sample": True,
        "ret_20": 0.01,
        "iv_rank_120": 0.5,
        "atm_iv_change_5": 0.0,
        "realised_return": -1.0,
        "tail_share": 0.2,
        "prob_profit": 0.3,
        "expected_return": 0.1,
        "kelly_fraction": 0.05,
        "growth_rate": 0.01,
        "growth_gap": 0.01,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def test_the_grid_has_every_combination_with_unique_ids() -> None:
    grid = rule_grid()
    assert len(grid) == 3 * 3 * 4 * 4 * 5 * 2 * 3 * 3 * 2 == 25_920
    assert len({r.rule_id for r in grid}) == len(grid)
    assert grid[0] == GrowthRule(top_n=3, right="call")
    assert grid[1].sizing == "kelly"
    rule = GrowthRule(
        rank_by="growth_gap",
        right="put",
        dte_band=(21, 45),
        moneyness_band=(0.97, 1.03),
        regime="calm",
        one_per_underlying_expiry=True,
        min_prob_profit=0.25,
        top_n=5,
        sizing="kelly",
    )
    assert rule.rule_id == "gg-put-d21_45-m97_103-calm-one-p25-n5-kelly"
    words = describe_rule(rule)
    assert words.startswith("Rank by calibrated minus market")
    assert "21 to 44 days" in words and "97% to below 103%" in words
    assert "at most 25% of equity" in words
    assert rule_fields(rule)["moneyness_band"] == "0.97-1.03"


@pytest.mark.parametrize(
    "fields",
    [
        {"rank_by": "x"},
        {"right": "x"},
        {"regime": "x"},
        {"sizing": "x"},
        {"dte_band": (5, 5)},
        {"min_prob_profit": 1.5},
        {"top_n": 0},
    ],
)
def test_rules_reject_bad_fields(fields: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        GrowthRule(**fields)  # type: ignore[arg-type]


def _slow_select(frame: pd.DataFrame, rule: GrowthRule) -> list[tuple[object, ...]]:
    """Row by row: gates, sort by score then cache order, one per group, top N per session."""
    keys = ["trade_date", "underlying", "expiration", "right", "strike"]
    rows = frame.loc[frame["is_out_of_sample"]].sort_values(keys, kind="stable")
    rows = rows.reset_index(drop=True)
    picked: list[tuple[object, ...]] = []
    for _, session in rows.groupby("trade_date", sort=True):
        candidates = []
        for position, r in session.iterrows():
            if rule.right != "both" and r["right"] != rule.right:
                continue
            if rule.dte_band and not rule.dte_band[0] <= r["dte_days"] < rule.dte_band[1]:
                continue
            band = rule.moneyness_band
            if band and not band[0] <= r["moneyness"] < band[1]:
                continue
            if rule.regime == "calm" and not r["atm_iv_change_5"] < CALM_MAX_IV_CHANGE:
                continue
            if rule.regime == "trend_up" and not r["ret_20"] > 0:
                continue
            if rule.regime == "high_iv_rank" and not r["iv_rank_120"] >= 2 / 3:
                continue
            if rule.regime == "low_iv_rank" and not r["iv_rank_120"] < 1 / 3:
                continue
            if rule.min_prob_profit > 0 and not r["prob_profit"] >= rule.min_prob_profit:
                continue
            score = r[rule.rank_by]
            candidates.append((math.inf if math.isnan(score) else -score, position, r))
        candidates.sort(key=lambda c: (c[0], c[1]))
        seen: set[tuple[object, ...]] = set()
        kept = 0
        for _, _, r in candidates:
            group = (r["underlying"], r["expiration"])
            if rule.one_per_underlying_expiry:
                if group in seen:
                    continue
                seen.add(group)
            if kept < rule.top_n:
                picked.append(tuple(r[k] for k in keys))
                kept += 1
    return picked


@st.composite
def _options(draw: st.DrawFn) -> pd.DataFrame:
    n = draw(st.integers(1, 20))
    maybe_nan = st.one_of(st.floats(-0.5, 0.5), st.just(float("nan")))
    rows = []
    for i in range(n):
        rows.append(
            {
                "underlying": draw(st.sampled_from(["SPY", "AAPL"])),
                "trade_date": pd.Timestamp("2021-03-01")
                + pd.Timedelta(days=draw(st.integers(0, 3))),
                "expiration": pd.Timestamp("2021-04-01")
                + pd.Timedelta(days=7 * draw(st.integers(0, 2))),
                "dte_days": draw(st.integers(7, 69)),
                "right": draw(st.sampled_from(["call", "put"])),
                "strike": float(i),
                "moneyness": draw(st.floats(0.88, 1.12)),
                "is_out_of_sample": draw(st.booleans()),
                "ret_20": draw(maybe_nan),
                "iv_rank_120": draw(st.one_of(st.floats(0, 1), st.just(float("nan")))),
                "atm_iv_change_5": draw(maybe_nan),
                "prob_profit": draw(st.floats(0, 1)),
                "expected_return": draw(st.sampled_from([0.1, 0.2, -0.3, float("nan")])),
                "growth_rate": draw(st.sampled_from([0.0, 0.01, 0.02])),
                "growth_gap": draw(st.floats(-0.01, 0.02)),
            }
        )
    return _frame(rows)


@settings(max_examples=150, deadline=None)
@given(
    frame=_options(),
    rank_by=st.sampled_from(RANK_BYS),
    right=st.sampled_from(["call", "put", "both"]),
    dte=st.sampled_from(DTE_BANDS),
    money=st.sampled_from(MONEYNESS_BANDS),
    regime=st.sampled_from(REGIME_GATES),
    one=st.booleans(),
    prob=st.sampled_from([0.0, 0.25, 0.4]),
    top_n=st.sampled_from([1, 3, 5]),
)
def test_selection_matches_a_slow_row_by_row_implementation(
    frame: pd.DataFrame,
    rank_by: str,
    right: str,
    dte: tuple[int, int] | None,
    money: tuple[float, float] | None,
    regime: str,
    one: bool,
    prob: float,
    top_n: int,
) -> None:
    rule = GrowthRule(
        rank_by=rank_by,  # type: ignore[arg-type]
        right=right,  # type: ignore[arg-type]
        dte_band=dte,
        moneyness_band=money,
        regime=regime,  # type: ignore[arg-type]
        one_per_underlying_expiry=one,
        min_prob_profit=prob,
        top_n=top_n,
    )
    prepared = prepare(frame)
    fast = prepared.frame.iloc[select_positions(prepared, rule)]
    keys = ["trade_date", "underlying", "expiration", "right", "strike"]
    assert [tuple(r) for r in fast[keys].itertuples(index=False)] == _slow_select(frame, rule)


def test_session_weights_split_equally_or_scale_kelly_to_the_cap() -> None:
    session = np.array([0, 0, 1, 2, 2, 2])
    kelly = np.array([0.2, 0.1, 0.05, 0.0, 0.0, 0.0])
    equal = session_weights(session, kelly, "equal")
    np.testing.assert_allclose(equal, [F_MAX / 2] * 2 + [F_MAX] + [F_MAX / 3] * 3)
    sized = session_weights(session, kelly, "kelly")
    np.testing.assert_allclose(sized, [0.2 * F_MAX / 0.3, 0.1 * F_MAX / 0.3, 0.05, 0, 0, 0])
    assert session_weights(np.zeros(0, dtype=np.int64), np.zeros(0), "kelly").shape == (0,)


def test_line_metrics_compound_the_session_returns() -> None:
    r = np.array([0.1, -0.5, 0.0, 0.2])
    m = line_metrics(r)
    assert m["growth_per_session"] == pytest.approx(np.log1p(r).mean())
    assert m["total_growth"] == pytest.approx(1.1 * 0.5 * 1.0 * 1.2 - 1)
    assert m["max_drawdown"] == pytest.approx(0.5)
    assert m["sharpe_per_session"] == pytest.approx(r.mean() / r.std(ddof=1))
    assert math.isnan(line_metrics(np.zeros(0))["growth_per_session"])
    assert math.isnan(line_metrics(np.array([0.1]))["sharpe_per_session"])


def test_evaluate_books_every_period_session_and_skips_unstaked_picks() -> None:
    frame = _frame(
        [
            {"trade_date": pd.Timestamp("2021-03-01"), "realised_return": 1.0},
            {"trade_date": pd.Timestamp("2021-03-01"), "strike": 105.0, "kelly_fraction": 0.0},
            {"trade_date": pd.Timestamp("2021-03-02"), "realised_return": -1.0, "growth_rate": -1},
            {
                "trade_date": pd.Timestamp("2022-03-01"),
                "realised_return": 3.0,
                "kelly_fraction": 0.5,
            },
            {"trade_date": pd.Timestamp("2022-03-02"), "is_out_of_sample": False},
        ]
    )
    prepared = prepare(frame)
    assert len(prepared.frame) == 4
    kelly = evaluate(
        prepared, GrowthRule(top_n=1, sizing="kelly"), dev_years=DEV, holdout_years=HOLD
    )
    assert set(kelly["dev"]) == set(METRICS)
    dev = kelly["dev"]
    # 2021-03-01 picks the growth_rate 0.01 option first (the 105 strike has kelly 0 but the
    # same score; the cache order puts 100 first), 2021-03-02 its only option.
    assert dev["n_trades"] == 2 and dev["n_sessions"] == 2
    assert dev["growth_per_session"] == pytest.approx(
        (math.log(1 + 0.05 * 1.0) + math.log(1 - 0.05)) / 2
    )
    assert dev["win_rate"] == 0.5 and dev["mean_return"] == 0.0
    hold = kelly["holdout"]
    assert hold["n_trades"] == 1
    assert hold["growth_per_session"] == pytest.approx(math.log(1 + F_MAX * 3.0))
    equal = evaluate(
        prepared, GrowthRule(top_n=2, sizing="equal"), dev_years=DEV, holdout_years=HOLD
    )
    assert equal["dev"]["n_trades"] == 3
    assert equal["dev"]["growth_per_session"] == pytest.approx(
        (math.log(1 + F_MAX * (1.0 - 1.0) / 2) + math.log(1 - F_MAX)) / 2
    )
    flat = flatten(equal)
    assert "growth_per_session_holdout" in flat
    with pytest.raises(ValueError, match="overlap"):
        evaluate(prepared, GrowthRule(), dev_years=DEV, holdout_years=DEV)


def test_intervals_only_for_rules_with_enough_dev_trades() -> None:
    frame = _frame(
        [
            {"trade_date": pd.Timestamp("2021-03-01") + pd.Timedelta(days=i), "realised_return": r}
            for i, r in enumerate([1.0, -1.0, 0.5, -1.0])
        ]
    )
    prepared = prepare(frame)
    positions = select_positions(prepared, GrowthRule())
    some = evaluate_positions(prepared, positions, "equal", dev_years=DEV, holdout_years=HOLD)
    assert not math.isnan(some["dev"]["mean_return_ci_low"])
    none = evaluate_positions(
        prepared, positions, "equal", dev_years=DEV, holdout_years=HOLD, ci_min_dev_trades=5
    )
    assert math.isnan(none["dev"]["mean_return_ci_low"])


def test_random_positions_are_seeded_and_capped_per_session() -> None:
    frame = _frame(
        [
            {"trade_date": pd.Timestamp("2021-03-01") + pd.Timedelta(days=i % 3), "strike": i}
            for i in range(30)
        ]
    )
    prepared = prepare(frame)
    a = random_positions(prepared, top_n=4, seed=1)
    b = random_positions(prepared, top_n=4, seed=1)
    np.testing.assert_array_equal(a, b)
    assert np.bincount(prepared.session[a]).tolist() == [4, 4, 4]
    assert not np.array_equal(a, random_positions(prepared, top_n=4, seed=2))
    with pytest.raises(ValueError):
        random_positions(prepared, top_n=0, seed=1)
    odd = (prepared.frame["strike"].to_numpy() % 2 == 1).astype(bool)
    only = random_positions(prepared, top_n=4, seed=1, eligible=odd)
    assert odd[only].all()
    assert np.bincount(prepared.session[only]).tolist() == [4, 4, 4]


def test_the_ladder_spreads_each_stake_over_its_open_sessions() -> None:
    expiry = pd.Timestamp("2022-01-20")
    frame = _frame(
        [
            {
                "trade_date": pd.Timestamp("2022-01-03"),
                "expiration": expiry,
                "realised_return": 1.0,
            },
            {
                "trade_date": pd.Timestamp("2022-01-04"),
                "expiration": expiry,
                "realised_return": -1.0,
            },
        ]
    )
    prepared = prepare(frame)
    np.testing.assert_array_equal(prepared.hold, [2, 1])
    positions = select_positions(prepared, GrowthRule())
    line = holdout_line(prepared, positions, "equal", HOLD)
    ladder = [1 + F_MAX / 2, (1 + F_MAX / 2) * (1 - F_MAX)]
    np.testing.assert_allclose(line["equity"], ladder)
    hold = evaluate_positions(prepared, positions, "equal", dev_years=DEV, holdout_years=HOLD)
    m = hold["holdout"]
    assert m["ladder_total_growth"] == pytest.approx(ladder[-1] - 1)
    assert m["ladder_max_drawdown"] == pytest.approx(F_MAX)
    assert m["ladder_growth_per_session"] == pytest.approx(np.log(ladder[-1]) / 2)
    bet = (np.log1p(F_MAX) + np.log1p(-F_MAX)) / 2
    assert m["growth_per_session"] == pytest.approx(bet)


def test_pick_rules_ranks_on_dev_growth_only() -> None:
    results = pd.DataFrame(
        {
            "rule_id": ["a", "b", "c", "d", "base"],
            "n_trades_dev": [500, 500, 100, 500, 500],
            "growth_per_session_dev": [0.003, 0.002, 0.01, 0.001, 0.0],
            "ladder_max_drawdown_dev": [0.5, 0.1, 0.1, 0.2, 0.3],
            "growth_per_session_holdout": [-0.001, 0.001, 0.5, 0.002, 0.0],
        }
    )
    picks = pick_rules(results, min_dev_trades=400)
    assert picks.qualified["rule_id"].tolist() == ["a", "b", "d", "base"]
    assert picks.best_growth == "a"
    assert picks.drawdown_median == pytest.approx(0.25)
    assert picks.best_low_drawdown == "b"
    assert picks.median_rule == "b"
    base = {str(k): v for k, v in results.iloc[4].items()}
    assert beat_counts(picks.qualified, base) == (3, 2)
    empty = pick_rules(results, min_dev_trades=10**6)
    assert empty.best_growth is None and empty.median_rule is None


def test_prepare_requires_the_columns() -> None:
    frame = _frame([{}]).drop(columns="growth_gap")
    with pytest.raises(ValueError, match="growth_gap"):
        prepare(frame)
    suffixed = _frame([{}])
    with pytest.raises(ValueError, match="_pooled"):
        prepare(suffixed, suffix="_pooled")
    assert set(OPTION_COLUMNS) <= set(_frame([{}]).columns)
