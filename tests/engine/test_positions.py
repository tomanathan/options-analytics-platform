import math
from datetime import date

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import RiskNeutralCdf, implied_cdf
from oap.engine.positions import (
    EVERYTHING,
    KIND_SPECS,
    Leg,
    Position,
    StructureKind,
    TailCompletedCdf,
    View,
    build,
    format_strike,
    score_structure,
    score_structures,
)
from oap.engine.spread_scoring import PutCreditSpread, score_spread
from tests.engine.chains import synthetic_chain

YEARS = 30 / 365
K = StructureKind


def _chain_cdf() -> RiskNeutralCdf:
    strikes, puts, calls, _ = synthetic_chain(100.0, 0.3, YEARS, 0.0, 0.25)
    keep = (strikes > 85) & (strikes < 115)
    return implied_cdf(
        strikes[keep],
        puts[keep],
        years=YEARS,
        rate=0.0,
        call_strikes=strikes[keep],
        call_mids=calls[keep],
    )


def _dist() -> TailCompletedCdf:
    return TailCompletedCdf.complete(_chain_cdf(), 0.35, 0.28)


def _closed_cdf() -> RiskNeutralCdf:
    """A CDF whose outer knots hold 0 and 1, so the tails carry no mass."""
    strikes = np.array([80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0])
    cdf = np.array([0.0, 0.08, 0.25, 0.5, 0.74, 0.9, 1.0])
    return RiskNeutralCdf(strikes, cdf, cdf, 100.0, YEARS, 0.0, 7, frozenset())


def _simpson(values: np.ndarray, h: float) -> float:
    return float(
        h / 3 * (values[0] + values[-1] + 4 * values[1:-1:2].sum() + 2 * values[2:-1:2].sum())
    )


def _quadrature(dist: TailCompletedCdf, position: Position) -> tuple[float, float, float]:
    """Composite Simpson between every knot and kink, and far into the upper tail."""
    breaks = sorted({0.0, *dist.base.strikes.tolist(), *position.kinks, 60.0 * dist.location})
    total = e1 = e2 = 0.0
    for a, b in zip(breaks[:-1], breaks[1:], strict=True):
        x = np.linspace(a, b, 20001)
        density = dist.density_array(np.clip(x, a + 1e-9, b - 1e-9))
        pnl = position.pnl(x)
        h = (b - a) / 20000
        total += _simpson(density, h)
        e1 += _simpson(pnl * density, h)
        e2 += _simpson(pnl * pnl * density, h)
    return total, e1, e2


# -- tail-completed distribution ----------------------------------------------------------


def test_tail_completed_cdf_is_a_distribution() -> None:
    dist = _dist()
    m_lo, m_hi = dist.tail_mass()
    assert m_lo > 0.01 and m_hi > 0.01
    x = np.linspace(0.0, 400.0, 40001)
    f = dist.prob_below_array(x)
    assert f[0] == 0.0
    assert np.all(np.diff(f) >= -1e-15)
    assert dist.prob_below(math.inf) == 1.0
    assert dist.prob_below(-5.0) == 0.0
    assert dist.prob_below(1e9) == pytest.approx(1.0, abs=1e-15)


def test_tail_completed_cdf_is_continuous_at_the_knots() -> None:
    dist = _dist()
    for knot in (dist.k_lo, dist.k_hi):
        for eps in (1e-6, 1e-9):
            assert dist.prob_below(knot - eps) == pytest.approx(dist.prob_below(knot), abs=1e-5)
            assert dist.prob_below(knot + eps) == pytest.approx(dist.prob_below(knot), abs=1e-5)
    assert dist.prob_below(dist.k_lo) == pytest.approx(dist.tail_mass()[0], abs=1e-15)
    assert 1.0 - dist.prob_below(dist.k_hi) == pytest.approx(dist.tail_mass()[1], abs=1e-15)


def test_inside_the_knots_the_base_cdf_is_unchanged() -> None:
    dist = _dist()
    x = np.linspace(dist.k_lo, dist.k_hi, 101)
    assert np.allclose(dist.prob_below_array(x), dist.base.prob_below_array(x), atol=0.0)


@pytest.mark.parametrize("p", [0.0005, 0.01, 0.05, 0.3, 0.5, 0.8, 0.95, 0.99, 0.9995])
def test_quantile_inverts_the_cdf_in_the_tails_and_inside(p: float) -> None:
    dist = _dist()
    assert dist.prob_below(dist.quantile(p)) == pytest.approx(p, abs=1e-9)


def test_quantile_ends() -> None:
    dist = _dist()
    assert dist.quantile(0.0) == 0.0
    assert dist.quantile(1.0) == math.inf
    with pytest.raises(EngineInputError):
        dist.quantile(1.5)


def test_zero_tail_mass_contributes_nothing() -> None:
    dist = TailCompletedCdf.complete(_closed_cdf(), 0.3, 0.3)
    assert dist.tail_mass() == (0.0, 0.0)
    assert dist.prob_below(50.0) == 0.0
    assert dist.prob_below(200.0) == 1.0
    assert dist.quantile(0.0) == 0.0
    assert dist.quantile(1.0) == pytest.approx(120.0)
    assert dist.density_array(np.array([50.0, 200.0])).tolist() == [0.0, 0.0]


def test_location_is_the_forward_or_the_median() -> None:
    cdf = _chain_cdf()
    assert TailCompletedCdf.complete(cdf, 0.3, 0.3).location == cdf.forward
    no_forward = RiskNeutralCdf(
        cdf.strikes, cdf.cdf, cdf.raw_cdf, math.nan, cdf.years, cdf.rate, 1, frozenset()
    )
    assert TailCompletedCdf.complete(no_forward, 0.3, 0.3).location == cdf.quantile(0.5)


def test_an_underflowed_tail_becomes_a_point_mass_at_the_knot() -> None:
    cdf = _chain_cdf()
    dist = TailCompletedCdf(cdf, 1e-4, 1e-4, 100.0)
    m_lo, m_hi = dist.tail_mass()
    assert dist.prob_below(dist.k_lo - 1.0) == 0.0
    assert dist.prob_below(dist.k_hi + 1.0) == 1.0
    call = build(K.LONG_CALL, [110.0], [1.0], YEARS)
    put = build(K.LONG_PUT, [90.0], [1.0], YEARS)
    total, e1_call, _ = dist.expect(call)
    _, e1_put, _ = dist.expect(put)
    assert total == pytest.approx(1.0, abs=1e-12)
    inside_call = dist.base.integrate_cdf(110.0, dist.k_hi)
    # E[(S - 110)+] = integral of (1 - F) above 110, and F is 1 above the point mass at k_n.
    assert e1_call == pytest.approx((dist.k_hi - 110.0) - inside_call - 1.0, abs=1e-9)
    assert e1_put == pytest.approx(dist.base.integrate_cdf(dist.k_lo, 90.0) - 1.0, abs=1e-9)
    assert m_hi > 0
    assert m_lo > 0


def test_invalid_tails_are_rejected() -> None:
    with pytest.raises(EngineInputError):
        TailCompletedCdf(_chain_cdf(), 0.0, 0.3, 100.0)
    with pytest.raises(EngineInputError):
        TailCompletedCdf(_chain_cdf(), 0.3, math.nan, 100.0)
    with pytest.raises(EngineInputError):
        TailCompletedCdf(_chain_cdf(), 0.3, 0.3, -1.0)


# -- expectations ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "strikes", "prices"),
    [
        (K.LONG_CALL, [105.0], [1.0]),
        (K.LONG_CALL, [125.0], [0.2]),
        (K.LONG_PUT, [95.0], [1.0]),
        (K.LONG_PUT, [80.0], [0.1]),
        (K.LONG_STRADDLE, [100.0], [3.0, 3.0]),
    ],
)
def test_expect_matches_quadrature_including_the_tails(
    kind: StructureKind, strikes: list[float], prices: list[float]
) -> None:
    dist = _dist()
    position = build(kind, strikes, prices, YEARS)
    total, e1, e2 = dist.expect(position)
    q_total, q_e1, q_e2 = _quadrature(dist, position)
    assert total == pytest.approx(1.0, abs=1e-12)
    assert q_total == pytest.approx(1.0, abs=1e-8)
    assert e1 == pytest.approx(q_e1, rel=1e-6)
    assert e2 == pytest.approx(q_e2, rel=1e-6)


def test_tail_partial_moments_match_quadrature() -> None:
    dist = _dist()
    edges = np.array([0.0, 40.0, dist.k_lo, dist.k_hi, 130.0])
    m0, c1, c2 = dist.segment_moments(np.unique(np.concatenate([edges, dist.base.strikes])))
    grid = np.unique(np.concatenate([edges, dist.base.strikes]))
    right = np.append(grid[1:], 60.0 * dist.location)
    for j in (0, 1, len(grid) - 2, len(grid) - 1):
        a, b = grid[j], right[j]
        x = np.linspace(a, b, 40001)
        density = dist.density_array(np.clip(x, a + 1e-9, b - 1e-9))
        h = (b - a) / 40000
        assert m0[j] == pytest.approx(_simpson(density, h), rel=1e-6, abs=1e-14)
        assert c1[j] == pytest.approx(_simpson((x - a) * density, h), rel=1e-6, abs=1e-12)
        assert c2[j] == pytest.approx(_simpson((x - a) ** 2 * density, h), rel=1e-6, abs=1e-10)


def test_expect_over_a_range_is_the_slice_of_the_whole() -> None:
    dist = _dist()
    position = build(K.IRON_CONDOR, [88.0, 92.0, 108.0, 112.0], [1.0, 0.5, 1.0, 0.5], YEARS)
    p_in, e1_in, e2_in = dist.expect(position, 92.0, 108.0)
    p_lo, e1_lo, e2_lo = dist.expect(position, None, 92.0)
    p_hi, e1_hi, e2_hi = dist.expect(position, 108.0, None)
    p_all, e1_all, e2_all = dist.expect(position)
    assert p_in == pytest.approx(dist.prob_between(92.0, 108.0), abs=1e-14)
    assert e1_in == pytest.approx(p_in * 1.0, abs=1e-12)
    assert p_in + p_lo + p_hi == pytest.approx(p_all, abs=1e-14)
    assert e1_in + e1_lo + e1_hi == pytest.approx(e1_all, abs=1e-12)
    assert e2_in + e2_lo + e2_hi == pytest.approx(e2_all, abs=1e-12)


def test_years_must_match() -> None:
    with pytest.raises(EngineInputError):
        _dist().expect(build(K.LONG_CALL, [100.0], [1.0], 2 * YEARS))


# -- put credit spread agreement ----------------------------------------------------------------


@pytest.mark.parametrize(("short", "long", "credit"), [(100.0, 95.0, 2.0), (105.0, 90.0, 6.0)])
def test_bull_put_spread_reproduces_score_spread_without_tail_mass(
    short: float, long: float, credit: float
) -> None:
    cdf = _closed_cdf()
    dist = TailCompletedCdf.complete(cdf, 0.3, 0.3)
    position = build(K.BULL_PUT_SPREAD, [long, short], [credit + 0.5, 0.5], YEARS)
    assert position.net_premium == pytest.approx(-credit)
    score = score_structure(position, dist, EVERYTHING)
    spread = PutCreditSpread("SPY", date(2024, 2, 1), short, long, credit, YEARS)
    reference = score_spread(spread, cdf, cash_apy=0.0)
    assert score.prob_profit == pytest.approx(reference.prob_profit, abs=1e-9)
    assert score.expected_pnl == pytest.approx(reference.expected_payoff, abs=1e-9)
    assert score.pnl_std == pytest.approx(reference.payoff_std, abs=1e-9)
    assert score.expected_return == pytest.approx(reference.expected_return_on_collateral, abs=1e-9)
    assert score.tail_share == 0.0


def test_bull_put_spread_inside_the_knots_ignores_the_tail_shape() -> None:
    cdf = _chain_cdf()
    position = build(K.BULL_PUT_SPREAD, [92.0, 97.0], [1.4, 0.5], YEARS)
    spread = PutCreditSpread("SPY", date(2024, 2, 1), 97.0, 92.0, 0.9, YEARS)
    reference = score_spread(spread, cdf, cash_apy=0.0)
    for sigma in (0.1, 0.3, 0.9):
        score = score_structure(position, TailCompletedCdf.complete(cdf, sigma, sigma), EVERYTHING)
        assert score.expected_pnl == pytest.approx(reference.expected_payoff, abs=1e-9)
        assert score.prob_profit == pytest.approx(reference.prob_profit, abs=1e-12)
        assert score.tail_share > 0.0


# -- positions ----------------------------------------------------------------------------------

HAND = [
    # kind, strikes, prices, net premium, max loss, max gain, breakevens, legs text
    (K.LONG_CALL, [100.0], [2.5], 2.5, 2.5, math.inf, (102.5,), "+1 C 100"),
    (K.LONG_PUT, [100.0], [2.5], 2.5, 2.5, 97.5, (97.5,), "+1 P 100"),
    (
        K.BULL_CALL_SPREAD,
        [100.0, 105.0],
        [3.0, 1.0],
        2.0,
        2.0,
        3.0,
        (102.0,),
        "+1 C 100 / -1 C 105",
    ),
    (K.BEAR_PUT_SPREAD, [95.0, 100.0], [3.0, 1.0], 2.0, 2.0, 3.0, (98.0,), "+1 P 100 / -1 P 95"),
    (
        K.BULL_PUT_SPREAD,
        [245.0, 250.0],
        [3.0, 1.0],
        -2.0,
        3.0,
        2.0,
        (248.0,),
        "-1 P 250 / +1 P 245",
    ),
    (
        K.BEAR_CALL_SPREAD,
        [100.0, 105.0],
        [3.0, 1.0],
        -2.0,
        3.0,
        2.0,
        (102.0,),
        "-1 C 100 / +1 C 105",
    ),
    (
        K.LONG_STRADDLE,
        [100.0],
        [3.0, 2.0],
        5.0,
        5.0,
        math.inf,
        (95.0, 105.0),
        "+1 C 100 / +1 P 100",
    ),
    (
        K.LONG_STRANGLE,
        [95.0, 105.0],
        [1.5, 1.0],
        2.5,
        2.5,
        math.inf,
        (92.5, 107.5),
        "+1 P 95 / +1 C 105",
    ),
    (
        K.IRON_CONDOR,
        [85.0, 90.0, 110.0, 115.0],
        [1.5, 0.5, 1.25, 0.25],
        -2.0,
        3.0,
        2.0,
        (88.0, 112.0),
        "-1 P 90 / +1 P 85 / -1 C 110 / +1 C 115",
    ),
]


@pytest.mark.parametrize(
    ("kind", "strikes", "prices", "premium", "loss", "gain", "breakevens", "text"), HAND
)
def test_hand_computed_positions(
    kind: StructureKind,
    strikes: list[float],
    prices: list[float],
    premium: float,
    loss: float,
    gain: float,
    breakevens: tuple[float, ...],
    text: str,
) -> None:
    position = build(kind, strikes, prices, YEARS)
    assert position.net_premium == pytest.approx(premium)
    assert position.max_loss == pytest.approx(loss)
    assert position.max_gain == pytest.approx(gain)
    assert position.breakevens == pytest.approx(breakevens)
    assert position.legs_text == text
    assert position.direction == KIND_SPECS[kind].direction
    assert position.kinks == tuple(sorted(set(strikes)))
    assert np.allclose(position.pnl(np.asarray(position.breakevens)), 0.0, atol=1e-12)


def test_slopes_per_kind() -> None:
    assert build(K.LONG_CALL, [100.0], [1.0], YEARS).slopes == (0, 1)
    assert build(K.LONG_PUT, [100.0], [1.0], YEARS).slopes == (-1, 0)
    assert build(K.LONG_STRADDLE, [100.0], [1.0, 1.0], YEARS).slopes == (-1, 1)
    assert build(K.BULL_PUT_SPREAD, [95.0, 100.0], [2.0, 1.0], YEARS).slopes == (0, 0)


def test_profit_intervals() -> None:
    straddle = build(K.LONG_STRADDLE, [100.0], [3.0, 2.0], YEARS)
    assert straddle.profit_intervals == ((0.0, 95.0), (105.0, math.inf))
    condor = build(K.IRON_CONDOR, [85.0, 90.0, 110.0, 115.0], [1.5, 0.5, 1.25, 0.25], YEARS)
    assert condor.profit_intervals == ((88.0, 112.0),)
    hopeless = build(K.BULL_CALL_SPREAD, [100.0, 101.0], [2.0, 0.5], YEARS)
    assert hopeless.profit_intervals == ()
    assert hopeless.max_gain == pytest.approx(-0.5)


def test_format_strike() -> None:
    assert format_strike(250.0) == "250"
    assert format_strike(182.5) == "182.5"
    assert format_strike(41.125) == "41.125"


def test_invalid_positions_are_rejected() -> None:
    with pytest.raises(EngineInputError):
        build(K.BULL_PUT_SPREAD, [100.0, 95.0], [1.0, 2.0], YEARS)
    with pytest.raises(EngineInputError):
        build(K.BULL_PUT_SPREAD, [95.0, 100.0], [6.0, 0.5], YEARS)  # credit above the width
    with pytest.raises(EngineInputError):
        build(K.LONG_CALL, [100.0], [0.0], YEARS)  # no risk
    with pytest.raises(EngineInputError):
        build(K.IRON_CONDOR, [85.0, 90.0, 110.0], [1.0, 0.5, 1.0, 0.5], YEARS)
    with pytest.raises(EngineInputError):
        build(K.LONG_CALL, [100.0], [1.0], 0.0)
    with pytest.raises(EngineInputError):
        Position(K.LONG_CALL, (Leg("C", 100.0, -1, 1.0),), YEARS)  # unbounded loss
    with pytest.raises(EngineInputError):
        Leg("X", 100.0, 1, 1.0)  # type: ignore[arg-type]
    with pytest.raises(EngineInputError):
        Leg("C", 100.0, 2, 1.0)
    with pytest.raises(EngineInputError):
        Leg("C", -1.0, 1, 1.0)


def test_views_validate() -> None:
    with pytest.raises(EngineInputError):
        View(105.0, 100.0)
    with pytest.raises(EngineInputError):
        View(None, None, True)
    with pytest.raises(EngineInputError):
        View(-1.0, None)
    assert View(None, 100.0).lo_or_zero == 0.0
    assert View(100.0, None).hi_or_inf == math.inf


# -- scores -------------------------------------------------------------------------------------


def test_conditional_returns() -> None:
    dist = TailCompletedCdf.complete(_closed_cdf(), 0.3, 0.3)
    call_spread = build(K.BULL_CALL_SPREAD, [100.0, 105.0], [3.0, 1.0], YEARS)
    above = score_structure(call_spread, dist, View(105.0, None))
    assert above.return_if_right == pytest.approx(1.5)  # gain 3 on a loss of 2
    assert above.prob_profit_given_view == pytest.approx(1.0)
    assert above.worst_in_view == pytest.approx(1.5)
    below = score_structure(call_spread, dist, View(None, 100.0))
    assert below.return_if_right == pytest.approx(-1.0)
    assert below.prob_profit_given_view == 0.0
    assert below.prob_view == pytest.approx(0.5)
    right = below.prob_view * below.return_if_right * 2.0
    wrong = (1.0 - below.prob_view) * below.return_if_wrong * 2.0
    assert right + wrong == pytest.approx(below.expected_pnl, abs=1e-12)


def test_empty_view_probability_gives_nan_conditionals() -> None:
    dist = TailCompletedCdf.complete(_closed_cdf(), 0.3, 0.3)
    call = build(K.LONG_CALL, [100.0], [2.0], YEARS)
    nowhere = score_structure(call, dist, View(130.0, None))
    assert nowhere.prob_view == 0.0
    assert math.isnan(nowhere.return_if_right)
    assert math.isnan(nowhere.prob_profit_given_view)
    assert nowhere.return_if_wrong == pytest.approx(nowhere.expected_return)
    everywhere = score_structure(call, dist, EVERYTHING)
    assert math.isnan(everywhere.return_if_wrong)


def test_worst_in_view_on_open_and_closed_views() -> None:
    dist = _dist()
    put_spread = build(K.BULL_PUT_SPREAD, [95.0, 100.0], [3.0, 1.0], YEARS)
    assert score_structure(put_spread, dist, View(None, 90.0)).worst_in_view == pytest.approx(-1.0)
    # Credit 2, breakeven 98, max loss 3.
    assert score_structure(put_spread, dist, View(97.0, 99.0)).worst_in_view == pytest.approx(
        -1.0 / 3.0
    )
    assert score_structure(put_spread, dist, View(98.0, 99.0)).worst_in_view == pytest.approx(0.0)
    assert score_structure(put_spread, dist, View(101.0, None)).worst_in_view == pytest.approx(
        2.0 / 3.0
    )
    call = build(K.LONG_CALL, [100.0], [2.0], YEARS)
    assert score_structure(call, dist, View(101.0, None)).worst_in_view == pytest.approx(-0.5)
    straddle = build(K.LONG_STRADDLE, [100.0], [3.0, 2.0], YEARS)
    move = score_structure(straddle, dist, View(90.0, 110.0, outside=True))
    assert move.worst_in_view == pytest.approx(1.0)
    assert move.prob_profit_given_view == pytest.approx(1.0)


def test_score_fields_are_consistent() -> None:
    dist = _dist()
    position = build(K.LONG_STRANGLE, [95.0, 105.0], [1.5, 1.0], YEARS)
    score = score_structure(position, dist, View(102.0, 110.0))
    _, e1, e2 = dist.expect(position)
    assert score.expected_pnl == pytest.approx(e1, abs=1e-14)
    assert score.pnl_std == pytest.approx(math.sqrt(e2 - e1 * e1), abs=1e-12)
    assert score.expected_return == pytest.approx(e1 / 2.5)
    assert score.reward_to_risk == pytest.approx(e1 / score.pnl_std)
    assert score.annualised_return == pytest.approx((1 + e1 / 2.5) ** (1 / YEARS) - 1)
    assert score.prob_profit == pytest.approx(
        dist.prob_below(92.5) + 1.0 - dist.prob_below(107.5), abs=1e-12
    )
    assert 0.0 < score.tail_share < 1.0


def test_batch_scoring_equals_one_at_a_time() -> None:
    dist = _dist()
    positions = [build(kind, s, p, YEARS) for kind, s, p, *_ in HAND]
    view = View(92.0, 104.0, outside=True)
    batch = score_structures(positions, dist, view)
    for position, scored in zip(positions, batch, strict=True):
        single = score_structure(position, dist, view)
        assert scored.position == single.position
        for name in (
            "prob_profit",
            "expected_pnl",
            "pnl_std",
            "prob_view",
            "prob_profit_given_view",
            "return_if_right",
            "return_if_wrong",
            "worst_in_view",
            "tail_share",
        ):
            assert getattr(scored, name) == pytest.approx(
                getattr(single, name), abs=1e-12, nan_ok=True
            ), name
    assert score_structures([], dist, view) == []


# -- properties ---------------------------------------------------------------------------------


def _floats(lo: float, hi: float) -> st.SearchStrategy[float]:
    return st.floats(lo, hi, allow_nan=False, allow_infinity=False)


@st.composite
def _condors(draw: st.DrawFn) -> Position:
    strikes = sorted(draw(st.lists(_floats(60.0, 140.0), min_size=4, max_size=4, unique=True)))
    if min(np.diff(strikes)) < 0.01:
        strikes = [60.0, 80.0, 120.0, 140.0]
    width = min(strikes[1] - strikes[0], strikes[3] - strikes[2])
    strikes = [strikes[1] - width, strikes[1], strikes[2], strikes[2] + width]
    credit = draw(_floats(0.01, 0.99)) * width
    return build(K.IRON_CONDOR, strikes, [credit, 0.0, 0.0, 0.0], YEARS)


@st.composite
def _positions(draw: st.DrawFn) -> Position:
    kind = draw(st.sampled_from([k for k in K if k != K.IRON_CONDOR]))
    spec = KIND_SPECS[kind]
    strikes = sorted(
        draw(st.lists(_floats(60.0, 140.0), min_size=spec.n_strikes, max_size=spec.n_strikes))
    )
    strikes = [s + 0.5 * i for i, s in enumerate(strikes)]
    if spec.premium == "debit":
        prices = [draw(_floats(0.05, 5.0)) if q > 0 else 0.0 for _, q, _ in spec.legs]
        return build(kind, strikes, prices, YEARS)
    width = strikes[-1] - strikes[0]
    prices = [draw(_floats(0.01, 0.99)) * width if q < 0 else 0.0 for _, q, _ in spec.legs]
    return build(kind, strikes, prices, YEARS)


@given(st.one_of(_positions(), _condors()), _floats(0.0, 1.0))
@settings(max_examples=150, deadline=None)
def test_pnl_is_piecewise_linear_between_kinks(position: Position, frac: float) -> None:
    points = [0.0, *position.kinks, position.kinks[-1] + 50.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        x = a + frac * (b - a)
        expected = (1 - frac) * position.pnl(np.asarray([a]))[0] + frac * position.pnl(
            np.asarray([b])
        )[0]
        assert position.pnl(np.asarray([x]))[0] == pytest.approx(expected, abs=1e-9)
    beyond = position.pnl(np.asarray([position.kinks[-1] + 1.0]))[0]
    at = position.pnl(np.asarray([position.kinks[-1]]))[0]
    assert beyond - at == pytest.approx(position.slopes[1], abs=1e-9)


@given(
    st.one_of(_positions(), _condors()),
    st.lists(_floats(50.0, 160.0), min_size=1, max_size=5, unique=True),
)
@settings(max_examples=100, deadline=None)
def test_expect_over_a_partition_sums_to_the_whole(position: Position, cuts: list[float]) -> None:
    dist = _dist()
    bounds: list[float | None] = [None, *sorted(cuts), None]
    total = [0.0, 0.0, 0.0]
    for lo, hi in zip(bounds[:-1], bounds[1:], strict=True):
        for i, value in enumerate(dist.expect(position, lo, hi)):
            total[i] += value
    whole = dist.expect(position)
    assert total[0] == pytest.approx(whole[0], abs=1e-12)
    assert total[1] == pytest.approx(whole[1], abs=1e-9)
    assert total[2] == pytest.approx(whole[2], rel=1e-9, abs=1e-9)
