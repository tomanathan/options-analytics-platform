import math
from dataclasses import replace
from datetime import date

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.engine.calibration import CalibrationMap
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import QualityFlag, RiskNeutralCdf, implied_cdf
from oap.engine.spread_scoring import (
    PutCreditSpread,
    SpreadScore,
    enumerate_spreads,
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


def _score(short: float, long: float, credit: float, prob_profit: float, ann: float) -> SpreadScore:
    return SpreadScore(
        spread=_spread(short, long, credit),
        prob_profit=prob_profit,
        prob_max_loss=0.0,
        expected_payoff=0.0,
        interest=0.0,
        expected_return_on_collateral=0.0,
        annualised_return=ann,
        kelly_fraction=0.0,
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
