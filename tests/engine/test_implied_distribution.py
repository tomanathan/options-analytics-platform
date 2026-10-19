import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.engine._types import FloatArray
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import (
    QualityFlag,
    RiskNeutralCdf,
    breeden_litzenberger_density,
    implied_cdf,
    usable_quotes,
)
from tests.engine.chains import lognormal_cdf, synthetic_chain

STRIKES = [90.0, 95.0, 100.0, 105.0]
MIDS = [0.5, 1.5, 3.5, 7.0]
YEARS = 30 / 365


def _f(lo: float, hi: float) -> st.SearchStrategy[float]:
    return st.floats(lo, hi, allow_nan=False, allow_infinity=False)


def _hand() -> RiskNeutralCdf:
    return implied_cdf(STRIKES, MIDS, years=YEARS, rate=0.0)


@st.composite
def _lognormal_chain(draw: st.DrawFn) -> tuple[float, float, float, float, float]:
    return (
        draw(_f(10, 1000)),
        draw(_f(0.05, 0.8)),
        draw(_f(7 / 365, 1)),
        draw(_f(0, 0.08)),
        draw(_f(0.05, 0.25)),
    )


@st.composite
def _arbitrary_chain(
    draw: st.DrawFn,
) -> tuple[FloatArray, FloatArray, float, float]:
    n = draw(st.integers(4, 30))
    start = draw(_f(1, 500))
    gaps = draw(st.lists(_f(0.5, 10), min_size=n - 1, max_size=n - 1))
    strikes = start + np.concatenate([[0.0], np.cumsum(gaps)])
    mids = np.array(draw(st.lists(_f(0, 100), min_size=n, max_size=n)))
    return strikes, mids, draw(_f(0, 0.1)), draw(_f(1 / 365, 3))


def test_hand_chain_knots_and_cdf() -> None:
    cdf = _hand()
    assert cdf.strikes.tolist() == [92.5, 97.5, 102.5]
    assert cdf.cdf.tolist() == pytest.approx([0.2, 0.4, 0.7])
    assert cdf.n_quotes == 4


def test_hand_chain_probabilities() -> None:
    cdf = _hand()
    assert cdf.prob_below(80) == pytest.approx(0.2)
    assert cdf.prob_below(95) == pytest.approx(0.3)
    assert cdf.prob_below(110) == pytest.approx(0.7)
    assert cdf.prob_between(95, 100) == pytest.approx(0.25)
    assert cdf.quantile(0.5) == pytest.approx(99.1666666667, abs=1e-9)
    assert cdf.expected_payoff_put_spread(100, 95) == pytest.approx(2.0625)


def test_hand_chain_forward_and_flags() -> None:
    cdf = _hand()
    assert math.isnan(cdf.forward)
    assert cdf.flags == {
        QualityFlag.NO_CALLS,
        QualityFlag.FORWARD_UNKNOWN,
        QualityFlag.SPARSE,
        QualityFlag.LEFT_TAIL_UNCOVERED,
        QualityFlag.RIGHT_TAIL_UNCOVERED,
    }


def test_rate_scales_raw_cdf_by_growth() -> None:
    cdf = implied_cdf(STRIKES, MIDS, years=1.0, rate=0.05)
    assert cdf.raw_cdf.tolist() == pytest.approx([0.21, 0.42, 0.735])


def test_prob_between_rejects_reversed_bounds() -> None:
    with pytest.raises(EngineInputError):
        _hand().prob_between(100, 95)


def test_quantile_rejects_out_of_range() -> None:
    cdf = _hand()
    for p in (1.1, -0.1, math.nan):
        with pytest.raises(EngineInputError):
            cdf.quantile(p)


def test_quantile_clamps_to_outer_knots() -> None:
    cdf = _hand()
    assert cdf.quantile(0.0) == 92.5
    assert cdf.quantile(1.0) == 102.5


def test_put_spread_payoff_rejects_reversed_strikes() -> None:
    with pytest.raises(EngineInputError):
        _hand().expected_payoff_put_spread(95, 100)


def test_density_is_piecewise_constant_between_knots() -> None:
    mid, dens = _hand().density()
    assert mid.tolist() == [95.0, 100.0]
    assert dens.tolist() == pytest.approx([0.04, 0.06])


def test_non_monotone_quotes_are_repaired() -> None:
    cdf = implied_cdf(STRIKES, [0.5, 1.6, 2.0, 7.0], years=YEARS, rate=0.0)
    assert cdf.raw_cdf.tolist() == pytest.approx([0.22, 0.08, 1.0])
    assert cdf.cdf.tolist() == pytest.approx([0.15, 0.15, 1.0])
    assert QualityFlag.MONOTONICITY_REPAIRED in cdf.flags


def test_values_above_one_are_clipped() -> None:
    cdf = implied_cdf(STRIKES, [0.5, 1.0, 1.5, 12.0], years=YEARS, rate=0.0)
    assert cdf.raw_cdf[-1] == pytest.approx(2.1)
    assert cdf.cdf[-1] == 1.0
    assert QualityFlag.CLIPPED in cdf.flags


@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        ({"put_strikes": [90, 95, 100]}, "three strikes"),
        ({"put_strikes": [90, 95, 95, 105]}, "duplicate strike"),
        ({"put_strikes": [90, 100, 95, 105]}, "decreasing strike"),
        ({"put_strikes": [0, 95, 100, 105]}, "zero strike"),
        ({"put_mids": [0.5, math.nan, 3.5, 7.0]}, "nan mid"),
        ({"put_mids": [0.5, -1.5, 3.5, 7.0]}, "negative mid"),
        ({"put_mids": [0.5, 1.5, 3.5]}, "length mismatch"),
        ({"put_mids": [[0.5, 1.5], [3.5, 7.0]]}, "2-D input"),
        ({"years": 0.0}, "years zero"),
        ({"rate": -1.0}, "rate minus one"),
        ({"call_strikes": [90, 100]}, "calls without mids"),
        ({"call_strikes": [100], "call_mids": [3.0]}, "one call strike"),
        ({"forward": 0.0}, "forward zero"),
    ],
)
def test_validation_errors(kwargs: dict[str, object], label: str) -> None:
    args: dict[str, object] = {
        "put_strikes": STRIKES,
        "put_mids": MIDS,
        "years": YEARS,
        "rate": 0.0,
    }
    args.update(kwargs)
    with pytest.raises(EngineInputError):
        implied_cdf(**args)  # type: ignore[arg-type]


def test_result_arrays_are_read_only() -> None:
    cdf = _hand()
    with pytest.raises(ValueError, match="read-only"):
        cdf.cdf[0] = 0.5


def test_constructor_rejects_non_monotone_cdf() -> None:
    with pytest.raises(EngineInputError):
        RiskNeutralCdf(
            strikes=np.array([1.0, 2.0]),
            cdf=np.array([0.5, 0.4]),
            raw_cdf=np.array([0.5, 0.4]),
            forward=math.nan,
            years=0.1,
            rate=0.0,
            n_quotes=2,
            flags=frozenset(),
        )


def test_usable_quotes_drops_bad_rows_and_computes_mids() -> None:
    strikes, mids = usable_quotes(
        [100, 90, 95, 105, 110, math.nan],
        [3.0, 0.4, 0.0, math.nan, 7.0, 1.0],
        [3.2, 0.6, 1.0, 9.0, 6.0, 2.0],
    )
    assert strikes.tolist() == [90.0, 100.0]
    assert mids.tolist() == pytest.approx([0.5, 3.1])


def test_usable_quotes_rejects_duplicate_strikes() -> None:
    with pytest.raises(EngineInputError):
        usable_quotes([100, 100], [1.0, 1.0], [1.2, 1.2])


@given(_arbitrary_chain())
def test_arbitrary_chains_give_valid_cdfs(
    data: tuple[FloatArray, FloatArray, float, float],
) -> None:
    strikes, mids, rate, years = data
    cdf = implied_cdf(strikes, mids, years=years, rate=rate)
    assert np.all(np.diff(cdf.strikes) > 0)
    assert np.all(np.diff(cdf.cdf) >= 0)
    assert cdf.cdf[0] >= 0 and cdf.cdf[-1] <= 1
    ks = np.sort(np.linspace(strikes[0] - 5, strikes[-1] + 5, 25))
    assert np.all(np.diff(cdf.prob_below_array(ks)) >= 0)
    a, b = float(ks[3]), float(ks[17])
    assert cdf.prob_between(a, b) >= 0
    assert cdf.prob_between(a, b) == pytest.approx(cdf.prob_below(b) - cdf.prob_below(a), abs=1e-15)
    for p in np.linspace(cdf.cdf[0], cdf.cdf[-1], 9):
        assert abs(cdf.prob_below(cdf.quantile(float(p))) - p) <= 1e-9
    _, density = cdf.density()
    for k in np.linspace(cdf.strikes[0], cdf.strikes[-1], 9):
        segment = min(int(np.searchsorted(cdf.strikes, k, side="right")) - 1, len(density) - 1)
        if density[segment] < 1e-6:
            # Inverting a CDF that is flat to rounding error (slope below 1e-6 per dollar)
            # amplifies float noise; flat stretches are covered by the quantile round trip.
            continue
        assert cdf.quantile(cdf.prob_below(float(k))) <= k + 1e-9
    with pytest.raises(EngineInputError):
        cdf.quantile(1.1)


@given(_lognormal_chain())
def test_recovers_lognormal_cdf(data: tuple[float, float, float, float, float]) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, _, forward = synthetic_chain(spot, vol, years, rate, step_frac)
    cdf = implied_cdf(strikes, puts, years=years, rate=rate)
    true_knots = lognormal_cdf(cdf.strikes, forward, vol, years)
    inside = (true_knots >= 0.02) & (true_knots <= 0.98)
    assert np.all(np.abs(cdf.cdf - true_knots)[inside] <= 0.005)
    grid = np.linspace(cdf.strikes[0], cdf.strikes[-1], 200)
    true_grid = lognormal_cdf(grid, forward, vol, years)
    inside_grid = (true_grid >= 0.02) & (true_grid <= 0.98)
    assert np.all(np.abs(cdf.prob_below_array(grid) - true_grid)[inside_grid] <= 0.015)


@given(_lognormal_chain())
def test_puts_plus_calls_matches_puts_only(data: tuple[float, float, float, float, float]) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, calls, forward = synthetic_chain(spot, vol, years, rate, step_frac)
    only_puts = implied_cdf(strikes, puts, years=years, rate=rate)
    both = implied_cdf(strikes, puts, years=years, rate=rate, call_strikes=strikes, call_mids=calls)
    assert both.strikes.tolist() == only_puts.strikes.tolist()
    assert both.cdf.tolist() == pytest.approx(only_puts.cdf.tolist(), abs=1e-9)
    assert abs(both.forward - forward) <= 1e-6 * spot
    assert QualityFlag.NO_CALLS not in both.flags
    assert QualityFlag.FORWARD_UNKNOWN not in both.flags


@given(_lognormal_chain())
def test_put_spread_payoff_matches_black_scholes(
    data: tuple[float, float, float, float, float],
) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, _, forward = synthetic_chain(spot, vol, years, rate, step_frac)
    cdf = implied_cdf(strikes, puts, years=years, rate=rate)
    growth = (1 + rate) ** years
    true_f = lognormal_cdf(strikes, forward, vol, years)
    ok = (true_f >= 0.02) & (true_f <= 0.98)
    idx = np.flatnonzero(ok)
    for a in idx[::3]:
        for b in idx[::4]:
            if b <= a:
                continue
            ks, kl = float(strikes[b]), float(strikes[a])
            expected = growth * (puts[b] - puts[a])
            assert abs(cdf.expected_payoff_put_spread(ks, kl) - expected) <= 0.015 * (ks - kl)


@given(_arbitrary_chain())
def test_breeden_litzenberger_telescopes(data: tuple[FloatArray, FloatArray, float, float]) -> None:
    strikes, mids, rate, years = data
    interior, dens = breeden_litzenberger_density(strikes, mids, years=years, rate=rate)
    raw = implied_cdf(strikes, mids, years=years, rate=rate).raw_cdf
    total = float(np.sum(dens * (strikes[2:] - strikes[:-2]) / 2))
    assert interior.tolist() == strikes[1:-1].tolist()
    assert total == pytest.approx(float(raw[-1] - raw[0]), abs=1e-9)


@given(_lognormal_chain())
def test_breeden_litzenberger_is_non_negative_on_synthetic_chains(
    data: tuple[float, float, float, float, float],
) -> None:
    spot, vol, years, rate, step_frac = data
    strikes, puts, calls, _ = synthetic_chain(spot, vol, years, rate, step_frac)
    for mids in (puts, calls):
        _, dens = breeden_litzenberger_density(strikes, mids, years=years, rate=rate)
        assert np.all(dens >= -1e-9)
