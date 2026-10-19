import math
from dataclasses import replace
from datetime import date

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.engine.calibration import CalibrationMap, apply_calibration
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import QualityFlag, RiskNeutralCdf, implied_cdf
from oap.engine.spread_scoring import (
    PutCreditSpread,
    SpreadScore,
    enumerate_spreads,
    put_spread_payoff_moments,
    rank_spreads,
    score_spread,
)
from tests.engine.chains import synthetic_chain

STRIKES = [90.0, 95.0, 100.0, 105.0]
MIDS = [0.5, 1.5, 3.5, 7.0]
YEARS = 30 / 365
EXPIRY = date(2024, 2, 1)


def _f(lo: float, hi: float) -> st.SearchStrategy[float]:
    return st.floats(lo, hi, allow_nan=False, allow_infinity=False)


def _hand_cdf() -> RiskNeutralCdf:
    return implied_cdf(STRIKES, MIDS, years=YEARS, rate=0.0)


def _spread(short: float = 100.0, long: float = 95.0, credit: float = 2.0) -> PutCreditSpread:
    return PutCreditSpread("SPY", EXPIRY, short, long, credit, YEARS)


def test_worked_example() -> None:
    spread = _spread()
    score = score_spread(spread, _hand_cdf(), cash_apy=0.036)
    assert spread.width == 5
    assert spread.max_loss == 3
    assert spread.collateral == 3
    assert spread.breakeven == 98
    assert score.prob_profit == pytest.approx(0.57, abs=1e-12)
    assert score.prob_max_loss == pytest.approx(0.3, abs=1e-12)
    assert score.expected_payoff == pytest.approx(-0.0625, abs=1e-12)
    assert score.interest == pytest.approx(0.008733352895680335, abs=1e-12)
    assert score.expected_return_on_collateral == pytest.approx(-0.017922215701439887, abs=1e-12)
    assert score.annualised_return == pytest.approx(-0.19750631365859123, abs=1e-12)
    assert score.kelly_fraction == 0.0
    assert score.extrapolated is False
    assert score.calibrated is False
    assert QualityFlag.NO_CALLS in score.flags


def test_worked_example_edge_and_risk() -> None:
    score = score_spread(_spread(), _hand_cdf(), cash_apy=0.036)
    first, second = put_spread_payoff_moments(_hand_cdf(), 100.0, 95.0)
    assert first == pytest.approx(2.0625, rel=1e-12)
    assert second == pytest.approx(445 / 48, rel=1e-12)
    assert score.fair_credit == pytest.approx(2.0625, rel=1e-12)
    assert score.expected_payoff == pytest.approx(-0.0625, rel=1e-12)
    assert score.edge_pct == pytest.approx(-0.03125, rel=1e-12)
    assert score.payoff_std == pytest.approx(2.2398498, rel=1e-7)
    assert score.payoff_std**2 == pytest.approx(445 / 48 - 2.0625**2, rel=1e-12)
    assert score.payoff_std**2 == pytest.approx(5.0169271, rel=1e-7)
    assert score.reward_to_risk == pytest.approx(-0.0279037, abs=1e-7)


def test_long_strike_below_lowest_knot_is_extrapolated() -> None:
    score = score_spread(_spread(long=90.0, credit=3.0), _hand_cdf(), cash_apy=0.036)
    assert score.extrapolated is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"credit": 0.0},
        {"credit": 5.0},
        {"long_strike": 100.0},
        {"long_strike": 101.0},
        {"years": 0.0},
        {"credit": math.nan},
        {"short_strike": math.inf},
        {"long_strike": 0.0},
    ],
)
def test_spread_validation(kwargs: dict[str, float]) -> None:
    args: dict[str, float] = {
        "short_strike": 100.0,
        "long_strike": 95.0,
        "credit": 2.0,
        "years": YEARS,
    }
    args.update(kwargs)
    with pytest.raises(EngineInputError):
        PutCreditSpread("SPY", EXPIRY, **args)


def test_score_rejects_mismatched_years() -> None:
    with pytest.raises(EngineInputError):
        score_spread(replace(_spread(), years=0.2), _hand_cdf(), cash_apy=0.036)


@pytest.mark.parametrize("apy", [-1.0, math.nan, math.inf])
def test_score_rejects_bad_cash_apy(apy: float) -> None:
    with pytest.raises(EngineInputError):
        score_spread(_spread(), _hand_cdf(), cash_apy=apy)


def test_identity_calibration_matches_uncalibrated() -> None:
    plain = score_spread(_spread(), _hand_cdf(), cash_apy=0.036)
    calibrated = score_spread(
        _spread(), _hand_cdf(), cash_apy=0.036, calibration=CalibrationMap.identity()
    )
    assert calibrated.calibrated is True
    assert QualityFlag.CALIBRATED in calibrated.flags
    for name in (
        "prob_profit",
        "prob_max_loss",
        "expected_payoff",
        "interest",
        "expected_return_on_collateral",
        "annualised_return",
        "kelly_fraction",
    ):
        assert getattr(calibrated, name) == pytest.approx(getattr(plain, name), abs=1e-12)


def test_enumerate_spreads_without_limits() -> None:
    spreads = enumerate_spreads("SPY", EXPIRY, YEARS, STRIKES, MIDS)
    got = [(s.short_strike, s.long_strike, s.credit) for s in spreads]
    assert got == [
        (95.0, 90.0, 1.0),
        (100.0, 90.0, 3.0),
        (100.0, 95.0, 2.0),
        (105.0, 90.0, 6.5),
        (105.0, 95.0, 5.5),
        (105.0, 100.0, 3.5),
    ]


def test_enumerate_spreads_width_and_credit_limits() -> None:
    assert len(enumerate_spreads("SPY", EXPIRY, YEARS, STRIKES, MIDS, max_width=5)) == 3
    assert len(enumerate_spreads("SPY", EXPIRY, YEARS, STRIKES, MIDS, min_width=10)) == 3
    credits = [
        s.credit for s in enumerate_spreads("SPY", EXPIRY, YEARS, STRIKES, MIDS, min_credit=2.0)
    ]
    assert 1.0 not in credits
    assert len(credits) == 5


def test_enumerate_spreads_excludes_credit_at_or_above_width() -> None:
    spreads = enumerate_spreads("SPY", EXPIRY, YEARS, [90, 95, 100], [0.1, 5.5, 5.0])
    # (95, 90) has credit 5.4 >= width 5; (100, 95) has a negative credit.
    assert [(s.short_strike, s.long_strike) for s in spreads] == [(100.0, 90.0)]


def test_enumerate_spreads_validates() -> None:
    with pytest.raises(EngineInputError):
        enumerate_spreads("SPY", EXPIRY, YEARS, [90], [1.0])
    with pytest.raises(EngineInputError):
        enumerate_spreads("SPY", EXPIRY, YEARS, [90, 95], [1.0, -1.0])
    with pytest.raises(EngineInputError):
        enumerate_spreads("SPY", EXPIRY, 0.0, [90, 95], [1.0, 2.0])


def _score(
    short: float,
    long: float,
    credit: float,
    prob_profit: float,
    ann: float,
    *,
    edge_pct: float = 0.0,
    reward_to_risk: float = 0.0,
) -> SpreadScore:
    return SpreadScore(
        spread=_spread(short, long, credit),
        prob_profit=prob_profit,
        prob_max_loss=0.0,
        expected_payoff=0.0,
        interest=0.0,
        expected_return_on_collateral=0.0,
        annualised_return=ann,
        kelly_fraction=0.0,
        fair_credit=0.0,
        edge_pct=edge_pct,
        payoff_std=1.0,
        reward_to_risk=reward_to_risk,
        calibrated=False,
        extrapolated=False,
        flags=frozenset(),
    )


def test_rank_spreads_orders_and_breaks_ties() -> None:
    a = _score(100, 95, 2.0, 0.6, 0.10)
    b = _score(100, 90, 2.0, 0.7, 0.10)
    c = _score(105, 100, 2.0, 0.7, 0.10)
    d = _score(105, 95, 2.0, 0.7, 0.10)
    e = _score(95, 90, 2.0, 0.9, 0.30)
    f = _score(110, 105, 2.0, 0.2, 0.50)
    ranked = rank_spreads([a, b, c, d, e, f], min_prob_profit=0.5)
    assert ranked == [e, d, c, b, a]
    assert rank_spreads([a, b, c, d, e, f])[0] is f


def test_rank_spreads_by_edge_orders_and_breaks_ties() -> None:
    a = _score(100, 95, 2.0, 0.6, 0.0, edge_pct=0.3)
    b = _score(100, 90, 2.0, 0.7, 0.0, edge_pct=0.3)
    c = _score(105, 100, 2.0, 0.7, 0.0, edge_pct=0.3)
    d = _score(105, 95, 2.0, 0.7, 0.0, edge_pct=0.3)
    e = _score(95, 90, 2.0, 0.9, 0.9, edge_pct=0.1)
    f = _score(110, 105, 2.0, 0.2, 0.0, edge_pct=0.8)
    assert rank_spreads([a, b, c, d, e, f], by="edge") == [f, d, c, b, a, e]
    assert rank_spreads([a, b, c, d, e, f], by="edge", min_prob_profit=0.5) == [d, c, b, a, e]


def test_rank_spreads_by_reward_to_risk_puts_nan_last() -> None:
    a = _score(100, 95, 2.0, 0.6, 0.0, reward_to_risk=0.4)
    b = _score(100, 90, 2.0, 0.7, 0.0, reward_to_risk=0.4)
    c = _score(105, 100, 2.0, 0.7, 0.0, reward_to_risk=0.4)
    d = _score(105, 95, 2.0, 0.9, 0.0, reward_to_risk=math.nan)
    e = _score(95, 90, 2.0, 0.5, 0.0, reward_to_risk=-0.2)
    f = _score(110, 105, 2.0, 0.2, 0.0, reward_to_risk=0.9)
    g = _score(90, 85, 2.0, 0.2, 0.0, reward_to_risk=math.nan)
    assert rank_spreads([a, b, c, d, e, f, g], by="reward_to_risk") == [f, c, b, a, e, d, g]


def test_rank_spreads_default_is_return() -> None:
    a = _score(100, 95, 2.0, 0.6, 0.1, edge_pct=0.9)
    b = _score(100, 90, 2.0, 0.7, 0.2, edge_pct=0.1)
    assert rank_spreads([a, b]) == rank_spreads([a, b], by="return") == [b, a]


@st.composite
def _lognormal_chain(draw: st.DrawFn) -> tuple[float, float, float, float, float]:
    return (
        draw(_f(10, 1000)),
        draw(_f(0.05, 0.8)),
        draw(_f(7 / 365, 1)),
        draw(_f(0, 0.08)),
        draw(_f(0.05, 0.25)),
    )


@given(_lognormal_chain())
def test_scores_on_synthetic_chain_are_coherent(
    data: tuple[float, float, float, float, float],
) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, _, forward = synthetic_chain(spot, vol, years, rate, step_frac)
    cdf = implied_cdf(strikes, puts, years=years, rate=rate)
    spreads = enumerate_spreads(
        "SPY", EXPIRY, years, strikes, puts, max_width=0.3 * forward, min_credit=1e-3 * spot
    )
    for spread in spreads[:: max(1, len(spreads) // 25)]:
        hi = score_spread(spread, cdf, cash_apy=0.05)
        lo = score_spread(spread, cdf, cash_apy=0.01)
        assert spread.max_loss + spread.credit == pytest.approx(spread.width, abs=1e-12)
        assert 0 <= hi.prob_max_loss <= 1 - hi.prob_profit + 1e-12 <= 1 + 1e-12
        assert -spread.max_loss - 1e-12 <= hi.expected_payoff <= spread.credit + 1e-12
        assert hi.interest >= 0
        assert hi.expected_return_on_collateral > -1
        assert hi.expected_return_on_collateral > lo.expected_return_on_collateral


def _assert_scale_invariant(
    data: tuple[float, float, float, float, float],
    c: float,
    *,
    roc_abs: float,
    ann_rel: float,
    ann_abs: float,
) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, _, forward = synthetic_chain(spot, vol, years, rate, step_frac)
    base_cdf = implied_cdf(strikes, puts, years=years, rate=rate)
    scaled_cdf = implied_cdf(strikes * c, puts * c, years=years, rate=rate)
    base = enumerate_spreads("SPY", EXPIRY, years, strikes, puts, max_width=0.3 * forward)
    for s0 in base[:: max(1, len(base) // 10)]:
        try:
            s1 = replace(
                s0,
                short_strike=s0.short_strike * c,
                long_strike=s0.long_strike * c,
                credit=s0.credit * c,
            )
        except EngineInputError:
            continue  # rounding pushed a credit at the edge of the width out of range
        a = score_spread(s0, base_cdf, cash_apy=0.036)
        b = score_spread(s1, scaled_cdf, cash_apy=0.036)
        assert b.prob_profit == pytest.approx(a.prob_profit, rel=1e-9, abs=1e-12)
        assert b.prob_max_loss == pytest.approx(a.prob_max_loss, rel=1e-9, abs=1e-12)
        assert b.expected_return_on_collateral == pytest.approx(
            a.expected_return_on_collateral, rel=1e-9, abs=roc_abs
        )
        assert b.annualised_return == pytest.approx(a.annualised_return, rel=ann_rel, abs=ann_abs)


@given(_lognormal_chain(), _f(0.01, 100))
def test_scores_are_scale_invariant(
    data: tuple[float, float, float, float, float], c: float
) -> None:
    # Multiplying strikes by an arbitrary c rounds each strike, about 1e-16 relative to its
    # size but up to 1e-13 relative to the strike spacing. The cancellation inside the return
    # on collateral magnifies that, and annualising magnifies it again by up to 1 / years.
    _assert_scale_invariant(data, c, roc_abs=1e-9, ann_rel=1e-7, ann_abs=1e-8)


@given(_lognormal_chain(), st.integers(-6, 6))
def test_scores_are_exactly_invariant_under_power_of_two_scaling(
    data: tuple[float, float, float, float, float], exponent: int
) -> None:
    # Scaling by a power of two is exact in binary floating point, so any difference would
    # come from the engine rather than from rounding the inputs.
    _assert_scale_invariant(data, 2.0**exponent, roc_abs=1e-12, ann_rel=1e-9, ann_abs=1e-12)


def test_scaling_helpers_are_numpy_arrays() -> None:
    strikes, puts, _, _ = synthetic_chain(100.0, 0.2, 0.1, 0.03, 0.1)
    assert isinstance(strikes, np.ndarray)
    assert strikes.shape == puts.shape


_TILT = CalibrationMap(
    knots=np.array([0.0, 0.05, 0.3, 0.7, 1.0]),
    values=np.array([0.0, 0.01, 0.2, 0.8, 1.0]),
    n_samples=100,
    is_identity=False,
)


def _flat_cdf(strikes: list[float], cdf: list[float]) -> RiskNeutralCdf:
    return RiskNeutralCdf(
        strikes=np.array(strikes),
        cdf=np.array(cdf),
        raw_cdf=np.array(cdf),
        forward=math.nan,
        years=YEARS,
        rate=0.0,
        n_quotes=len(strikes),
        flags=frozenset(),
    )


def test_constant_cdf_below_the_lowest_knot() -> None:
    c, width = 0.2, 10.0
    cdf = _flat_cdf([100.0, 110.0], [c, 0.5])
    first, second = put_spread_payoff_moments(cdf, 90.0, 80.0)
    assert first == pytest.approx(c * width, rel=1e-12)
    assert second == pytest.approx(c * width**2, rel=1e-12)
    score = score_spread(PutCreditSpread("SPY", EXPIRY, 90.0, 80.0, 3.0, YEARS), cdf, cash_apy=0.0)
    assert score.payoff_std**2 == pytest.approx(c * (1 - c) * width**2, rel=1e-12)
    assert score.fair_credit == pytest.approx(2.0, rel=1e-12)


def test_zero_probability_gives_zero_std_and_nan_reward_to_risk() -> None:
    cdf = _flat_cdf([100.0, 110.0], [0.0, 0.5])
    score = score_spread(PutCreditSpread("SPY", EXPIRY, 90.0, 80.0, 3.0, YEARS), cdf, cash_apy=0.0)
    assert score.fair_credit == 0.0
    assert score.payoff_std == 0.0
    assert math.isnan(score.reward_to_risk)
    assert score.edge_pct == 1.0


def test_moments_reject_inverted_strikes() -> None:
    with pytest.raises(EngineInputError):
        put_spread_payoff_moments(_hand_cdf(), 95.0, 100.0)


def _brute_force_moments(cdf: RiskNeutralCdf, k_short: float, k_long: float) -> tuple[float, float]:
    """Stieltjes midpoint sums over 20,000 cells on the strikes plus the atom below them."""
    width = k_short - k_long
    edges = np.linspace(k_long, k_short, 20_001)
    mass = np.diff(cdf.prob_below_array(edges))
    payoff = k_short - 0.5 * (edges[:-1] + edges[1:])
    atom = float(cdf.prob_below(k_long))
    first = float(np.sum(mass * payoff)) + atom * width
    second = float(np.sum(mass * payoff**2)) + atom * width**2
    return first, second


@given(_lognormal_chain())
def test_moments_match_brute_force_on_raw_and_calibrated_cdfs(
    data: tuple[float, float, float, float, float],
) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, _, forward = synthetic_chain(spot, vol, years, rate, step_frac)
    raw = implied_cdf(strikes, puts, years=years, rate=rate)
    spreads = enumerate_spreads(
        "SPY", EXPIRY, years, strikes, puts, max_width=0.3 * forward, min_credit=1e-3 * spot
    )
    for cdf in (raw, apply_calibration(raw, _TILT)):
        for spread in spreads[:: max(1, len(spreads) // 5)]:
            width = spread.width
            first, second = put_spread_payoff_moments(cdf, spread.short_strike, spread.long_strike)
            bf_first, bf_second = _brute_force_moments(cdf, spread.short_strike, spread.long_strike)
            assert abs(first - bf_first) <= 1e-6 * width
            assert abs(second - bf_second) <= 1e-6 * width**2
            var = max(0.0, second - first**2)
            assert abs(var - max(0.0, bf_second - bf_first**2)) <= 1e-6 * width**2


@given(_lognormal_chain(), st.booleans())
def test_edge_and_risk_bounds(
    data: tuple[float, float, float, float, float], calibrated: bool
) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, _, forward = synthetic_chain(spot, vol, years, rate, step_frac)
    cdf = implied_cdf(strikes, puts, years=years, rate=rate)
    spreads = enumerate_spreads(
        "SPY", EXPIRY, years, strikes, puts, max_width=0.3 * forward, min_credit=1e-3 * spot
    )
    for spread in spreads[:: max(1, len(spreads) // 25)]:
        score = score_spread(spread, cdf, cash_apy=0.036, calibration=_TILT if calibrated else None)
        w = spread.width
        assert -1e-12 * w <= score.fair_credit <= w * (1 + 1e-12)
        assert score.edge_pct <= 1.0
        assert 0.0 <= score.payoff_std <= w / 2 * (1 + 1e-12)
        assert abs(score.fair_credit + score.expected_payoff - spread.credit) <= 1e-12 * max(1.0, w)
        if score.payoff_std > 0:
            assert score.reward_to_risk * score.expected_payoff >= 0.0
        else:
            assert math.isnan(score.reward_to_risk)


@st.composite
def _fair_chain(draw: st.DrawFn) -> tuple[float, float, float, float]:
    return (draw(_f(10, 1000)), draw(_f(0.05, 0.8)), draw(_f(7 / 365, 1)), draw(_f(0.05, 0.1)))


@given(_fair_chain())
def test_spreads_priced_off_the_own_chain_have_small_edge(
    data: tuple[float, float, float, float],
) -> None:
    # With rate 0 the credit is not discounted relative to the fair credit, so the only
    # difference is the interpolation between knots.
    spot, vol, years, step_frac = data
    strikes, puts, _, forward = synthetic_chain(spot, vol, years, 0.0, step_frac)
    cdf = implied_cdf(strikes, puts, years=years, rate=0.0)
    spreads = enumerate_spreads(
        "SPY", EXPIRY, years, strikes, puts, max_width=0.3 * forward, min_credit=1e-3 * spot
    )
    for spread in spreads[:: max(1, len(spreads) // 25)]:
        if spread.long_strike < cdf.strikes[0]:
            continue
        score = score_spread(spread, cdf, cash_apy=0.0)
        assert abs(score.expected_payoff) <= 2e-3 * spread.width
        if spread.credit >= 0.05 * spread.width:
            assert abs(score.edge_pct) <= 0.03


@given(_lognormal_chain(), _f(0.01, 100))
def test_fair_credit_and_risk_scale_with_the_price_level(
    data: tuple[float, float, float, float, float], c: float
) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, _, forward = synthetic_chain(spot, vol, years, rate, step_frac)
    base_cdf = implied_cdf(strikes, puts, years=years, rate=rate)
    scaled_cdf = implied_cdf(strikes * c, puts * c, years=years, rate=rate)
    base = enumerate_spreads("SPY", EXPIRY, years, strikes, puts, max_width=0.3 * forward)
    for s0 in base[:: max(1, len(base) // 10)]:
        try:
            s1 = replace(
                s0,
                short_strike=s0.short_strike * c,
                long_strike=s0.long_strike * c,
                credit=s0.credit * c,
            )
        except EngineInputError:
            continue
        a = score_spread(s0, base_cdf, cash_apy=0.036)
        b = score_spread(s1, scaled_cdf, cash_apy=0.036)
        assert b.fair_credit == pytest.approx(a.fair_credit * c, rel=1e-6, abs=1e-9)
        assert b.payoff_std == pytest.approx(a.payoff_std * c, rel=1e-6, abs=1e-9 * c)
        assert b.edge_pct == pytest.approx(a.edge_pct, rel=1e-6, abs=1e-9)
        if math.isnan(a.reward_to_risk):
            continue
        assert b.reward_to_risk == pytest.approx(a.reward_to_risk, rel=1e-6, abs=1e-9)


def test_pop_implied_worked_example() -> None:
    # Width 5, credit 2, max loss 3: odds 2 to 3, breakeven probability 3 / 5.
    assert _spread().pop_implied == pytest.approx(0.6, abs=1e-15)


@given(_f(1, 1000), _f(0.01, 100), _f(0.001, 0.999))
def test_pop_implied_is_one_minus_credit_share_of_width(
    short: float, width: float, credit_share: float
) -> None:
    long = short - width
    if long <= 0:
        return
    spread = PutCreditSpread("SPY", EXPIRY, short, long, credit_share * width, YEARS)
    assert 0.0 < spread.pop_implied < 1.0
    assert spread.pop_implied == pytest.approx(1.0 - spread.credit / spread.width, abs=1e-12)
