import itertools
import math
import re

import numpy as np
import pytest

from oap.engine.black_scholes import call_price, put_price
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import RiskNeutralCdf
from oap.engine.positions import (
    KIND_SPECS,
    Position,
    StructureKind,
    StructureScore,
    TailCompletedCdf,
    View,
    build,
    score_structures,
)
from oap.engine.structures import (
    REASON_TEMPLATES,
    SPREAD_KINDS,
    ChainSide,
    best_per_kind,
    dominance,
    enumerate_structures,
    qualifies,
    ranked,
    verdict,
)

K = StructureKind
YEARS = 30 / 365
CLOSE = 100.0
STRIKES = np.arange(80.0, 120.01, 5.0)
HALF_SPREAD = 0.05
BANNED = ("buy", "sell", "recommend", "should")


def _side(prices: np.ndarray) -> ChainSide:
    return ChainSide(STRIKES.copy(), np.maximum(prices - HALF_SPREAD, 0.01), prices + HALF_SPREAD)


def _chain() -> tuple[ChainSide, ChainSide]:
    calls = call_price(CLOSE, STRIKES, YEARS, 0.0, 0.3)
    puts = put_price(CLOSE, STRIKES, YEARS, 0.0, 0.3)
    return _side(np.asarray(calls)), _side(np.asarray(puts))


def _enumerate(**overrides: object) -> list[Position]:
    calls, puts = _chain()
    args: dict[str, object] = {
        "close": CLOSE,
        "years": YEARS,
        "knot_lo": 70.0,
        "knot_hi": 130.0,
        "fill": "natural",
    }
    args.update(overrides)
    return enumerate_structures(calls, puts, **args)  # type: ignore[arg-type]


def _by_kind(positions: list[Position]) -> dict[StructureKind, list[Position]]:
    out: dict[StructureKind, list[Position]] = {k: [] for k in K}
    for p in positions:
        out[p.kind].append(p)
    return out


def _closed_dist() -> TailCompletedCdf:
    strikes = np.array([70.0, 85.0, 95.0, 100.0, 105.0, 115.0, 130.0])
    cdf = np.array([0.0, 0.06, 0.3, 0.5, 0.7, 0.94, 1.0])
    base = RiskNeutralCdf(strikes, cdf, cdf, 100.0, YEARS, 0.0, 7, frozenset())
    return TailCompletedCdf.complete(base, 0.3, 0.3)


# -- enumeration ------------------------------------------------------------------------------


def test_counts_per_kind_match_a_brute_force_count() -> None:
    calls, puts = _chain()
    groups = _by_kind(_enumerate(max_width_fraction=0.10))
    ca = dict(zip(STRIKES, calls.asks, strict=True))  # long call fill (natural)
    cb = dict(zip(STRIKES, calls.bids, strict=True))  # short call fill
    pa = dict(zip(STRIKES, puts.asks, strict=True))
    pb = dict(zip(STRIKES, puts.bids, strict=True))
    n = STRIKES.shape[0]
    assert len(groups[K.LONG_CALL]) == n
    assert len(groups[K.LONG_PUT]) == n
    pairs = [(a, b) for a, b in itertools.combinations(STRIKES, 2) if b - a <= 10.0]
    expected = {
        K.BULL_CALL_SPREAD: sum(1 for a, b in pairs if ca[a] - cb[b] > 0),
        K.BEAR_CALL_SPREAD: sum(1 for a, b in pairs if 0 < cb[a] - ca[b] < b - a),
        K.BEAR_PUT_SPREAD: sum(1 for a, b in pairs if pa[b] - pb[a] > 0),
        K.BULL_PUT_SPREAD: sum(1 for a, b in pairs if 0 < pb[b] - pa[a] < b - a),
    }
    for kind, count in expected.items():
        assert len(groups[kind]) == count > 0, kind
    assert len(groups[K.LONG_STRADDLE]) == 5  # 90, 95, 100, 105, 110
    below = [k for k in STRIKES if 85.0 <= k < 100.0]
    above = [k for k in STRIKES if 100.0 < k <= 115.0]
    assert len(groups[K.LONG_STRANGLE]) == len(below) * len(above)
    put_wings = [(a, b) for a, b in pairs if b < 100.0]
    call_wings = [(a, b) for a, b in pairs if a > 100.0]
    condors = sum(
        1
        for (p1, p2), (c1, c2) in itertools.product(put_wings, call_wings)
        if p2 - p1 == c2 - c1 and 0 < pb[p2] - pa[p1] + cb[c1] - ca[c2] < p2 - p1
    )
    assert len(groups[K.IRON_CONDOR]) == condors > 0


def test_max_per_kind_caps_each_kind_nearest_the_close_first() -> None:
    groups = _by_kind(_enumerate(max_per_kind=3))
    for kind, positions in groups.items():
        assert len(positions) <= 3, kind
    assert sorted(p.kinks[0] for p in groups[K.LONG_CALL]) == [95.0, 100.0, 105.0]
    assert groups[K.LONG_STRADDLE][0].kinks == (100.0,)
    first_condor = groups[K.IRON_CONDOR][0]
    assert first_condor.kinks[1:3] == (95.0, 105.0)
    assert first_condor.kinks[1] - first_condor.kinks[0] == 5.0


def test_every_strike_lies_inside_the_knots() -> None:
    positions = _enumerate(knot_lo=87.0, knot_hi=112.0)
    assert positions
    for p in positions:
        assert all(87.0 <= k <= 112.0 for k in p.kinks)


def test_debit_and_credit_signs_and_finite_risk() -> None:
    for fill in ("natural", "mid"):
        for p in _enumerate(fill=fill):
            spec = KIND_SPECS[p.kind]
            if spec.premium == "debit":
                assert p.net_premium > 0
            else:
                assert p.net_premium < 0
            assert 0 < p.max_loss < math.inf


def test_free_lunches_are_dropped() -> None:
    calls, puts = _chain()
    # A put ask at 105 far below the bid at 100: the 100/105 bear put spread would pay to hold.
    asks = puts.asks.copy()
    asks[STRIKES == 105.0] = 0.02
    bids = np.minimum(puts.bids, asks)
    cheap = ChainSide(STRIKES.copy(), bids, asks)
    positions = enumerate_structures(
        calls, cheap, close=CLOSE, years=YEARS, knot_lo=70.0, knot_hi=130.0, fill="natural"
    )
    bear_puts = [p for p in positions if p.kind == K.BEAR_PUT_SPREAD]
    assert all(p.net_premium > 0 for p in bear_puts)
    assert not any(p.kinks == (100.0, 105.0) for p in bear_puts)


def test_fills_by_side() -> None:
    calls, puts = _chain()
    natural = _by_kind(_enumerate(fill="natural"))
    mid = _by_kind(_enumerate(fill="mid"))
    spread = next(p for p in natural[K.BULL_CALL_SPREAD] if p.kinks == (95.0, 105.0))
    i95, i105 = int(np.flatnonzero(STRIKES == 95.0)[0]), int(np.flatnonzero(STRIKES == 105.0)[0])
    assert spread.legs[0].price == calls.asks[i95]  # long at the ask
    assert spread.legs[1].price == calls.bids[i105]  # short at the bid
    credit = next(p for p in natural[K.BULL_PUT_SPREAD] if p.kinks == (95.0, 105.0))
    assert credit.legs[0].price == puts.bids[i105]
    assert credit.legs[1].price == puts.asks[i95]
    mid_spread = next(p for p in mid[K.BULL_CALL_SPREAD] if p.kinks == (95.0, 105.0))
    assert mid_spread.legs[0].price == pytest.approx(0.5 * (calls.bids[i95] + calls.asks[i95]))
    assert mid_spread.legs[1].price == pytest.approx(0.5 * (calls.bids[i105] + calls.asks[i105]))
    assert mid_spread.net_premium < spread.net_premium


def test_a_leg_with_a_zero_fill_is_skipped() -> None:
    calls, puts = _chain()
    bids = calls.bids.copy()
    bids[STRIKES == 120.0] = 0.0
    zero = ChainSide(STRIKES.copy(), bids, calls.asks)
    positions = enumerate_structures(
        zero, puts, close=CLOSE, years=YEARS, knot_lo=70.0, knot_hi=130.0, fill="natural"
    )
    for p in positions:
        for leg in p.legs:
            assert leg.price > 0
    shorts_at_120 = [
        p
        for p in positions
        if any(leg.right == "C" and leg.quantity < 0 and leg.strike == 120.0 for leg in p.legs)
    ]
    assert shorts_at_120 == []
    assert any(p.kind == K.LONG_CALL and p.kinks == (120.0,) for p in positions)


def test_enumeration_validates_its_inputs() -> None:
    with pytest.raises(EngineInputError):
        _enumerate(close=0.0)
    with pytest.raises(EngineInputError):
        _enumerate(knot_lo=120.0, knot_hi=80.0)
    with pytest.raises(EngineInputError):
        _enumerate(fill="best")
    with pytest.raises(EngineInputError):
        _enumerate(max_per_kind=0)
    with pytest.raises(EngineInputError):
        ChainSide(np.array([100.0, 95.0]), np.array([1.0, 1.0]), np.array([1.1, 1.1]))
    with pytest.raises(EngineInputError):
        ChainSide(np.array([95.0, 100.0]), np.array([1.0, 1.0]), np.array([0.9, 1.1]))


def test_an_empty_side_gives_no_structures_that_need_it() -> None:
    calls, _ = _chain()
    empty = ChainSide(np.zeros(0), np.zeros(0), np.zeros(0))
    positions = enumerate_structures(
        calls, empty, close=CLOSE, years=YEARS, knot_lo=70.0, knot_hi=130.0, fill="mid"
    )
    kinds = {p.kind for p in positions}
    assert kinds == {K.LONG_CALL, K.BULL_CALL_SPREAD, K.BEAR_CALL_SPREAD}


# -- comparison -----------------------------------------------------------------------------


def _scores(
    view: View, min_pop: float = 0.5
) -> tuple[dict[StructureKind, StructureScore], list[StructureScore]]:
    dist = _closed_dist()
    scores = score_structures(_enumerate(fill="mid"), dist, view)
    return best_per_kind(scores, min_prob_profit_given_view=min_pop), scores


def test_best_per_kind_keeps_the_highest_return_if_right_that_qualifies() -> None:
    dist = _closed_dist()
    view = View(103.0, 112.0)
    scores = score_structures(_enumerate(fill="mid"), dist, view)
    bests = best_per_kind(scores, min_prob_profit_given_view=0.6)
    assert list(bests) == [k for k in K if k in bests]
    for kind, best in bests.items():
        same = [s for s in scores if s.position.kind == kind and qualifies(s, 0.6)]
        assert best.return_if_right == max(s.return_if_right for s in same)
        assert best.prob_profit_given_view >= 0.6
    assert K.BULL_CALL_SPREAD in bests and K.LONG_CALL in bests
    order = ranked(scores, min_prob_profit_given_view=0.6)
    assert [s.return_if_right for s in order] == sorted(
        (s.return_if_right for s in order), reverse=True
    )
    assert best_per_kind(scores, min_prob_profit_given_view=1.01) == {}


def test_dominance_segments_merge_and_cover_the_grid() -> None:
    dist = _closed_dist()
    view = View(None, None, False)
    scores = score_structures(
        [
            build(K.LONG_CALL, [100.0], [2.0], YEARS),
            build(K.LONG_PUT, [100.0], [2.0], YEARS),
            build(K.BULL_PUT_SPREAD, [95.0, 100.0], [2.0, 0.5], YEARS),
        ],
        dist,
        view,
    )
    bests = {s.position.kind: s for s in scores}
    grid = np.linspace(80.0, 120.0, 161)
    segments = dominance(bests, grid)
    assert segments[0][0] == 80.0 and segments[-1][1] == 120.0
    for (a, b, kind), (c, _, other) in zip(segments[:-1], segments[1:], strict=True):
        assert a < b == c
        assert kind != other
    kinds = [k for _, _, k in segments]
    assert kinds[0] == K.LONG_PUT and kinds[-1] == K.LONG_CALL
    assert K.BULL_PUT_SPREAD in kinds
    assert dominance({}, grid) == []


def test_verdict_spread_wins_a_bounded_up_view() -> None:
    bests, _ = _scores(View(103.0, 110.0))
    result = verdict(bests, View(103.0, 110.0))
    assert result.best_spread_kind in SPREAD_KINDS
    assert result.best_single_kind == K.LONG_CALL
    assert result.advantage == pytest.approx(
        result.spread_return_if_right - result.single_return_if_right
    )
    assert result.advantage > 0
    assert "$110.00" in result.reason
    assert f"{result.spread_return_if_right:.2f}x" in result.reason
    assert f"{result.single_return_if_right:.2f}x" in result.reason


def test_verdict_rule_selection() -> None:
    dist = _closed_dist()
    call = build(K.LONG_CALL, [100.0], [2.0], YEARS)
    put = build(K.LONG_PUT, [100.0], [2.0], YEARS)
    bull = build(K.BULL_CALL_SPREAD, [100.0, 105.0], [2.0, 0.5], YEARS)
    bear = build(K.BEAR_PUT_SPREAD, [95.0, 100.0], [2.0, 0.5], YEARS)
    straddle = build(K.LONG_STRADDLE, [100.0], [2.0, 2.0], YEARS)

    def run(positions: list[Position], view: View) -> str:
        scores = score_structures(positions, dist, view)
        bests = best_per_kind(scores, min_prob_profit_given_view=0.0)
        result = verdict(bests, view)
        for template_id, template in REASON_TEMPLATES.items():
            pattern = re.escape(template)
            for name in ("lo", "hi", "spread", "single", "spread_r", "single_r"):
                pattern = pattern.replace(re.escape("{" + name + "}"), ".*")
            if re.fullmatch(pattern, result.reason):
                return template_id
        raise AssertionError(result.reason)

    assert run([call, bull], View(101.0, 106.0)) == "spread_capped_above"
    assert run([put, bear], View(94.0, 99.0)) == "spread_capped_below"
    assert run([call, bull], View(118.0, None)) == "single_open_above"
    assert run([put, bear], View(None, 82.0)) == "single_open_below"
    assert run([straddle, bull], View(85.0, 115.0, outside=True)) == "single_move"
    assert run([call], View(101.0, 106.0)) == "no_spread"
    assert run([bull], View(101.0, 106.0)) == "no_single"
    assert run([], View(101.0, 106.0)) == "none"
    assert run([straddle, bull], View(118.0, None, outside=True)) == "single_uncapped"


def test_verdict_with_one_side_missing_has_nan_advantage() -> None:
    dist = _closed_dist()
    view = View(103.0, 110.0)
    scores = score_structures([build(K.LONG_CALL, [100.0], [2.0], YEARS)], dist, view)
    result = verdict(best_per_kind(scores, min_prob_profit_given_view=0.0), view)
    assert result.best_spread_kind is None
    assert result.best_kind == K.LONG_CALL
    assert math.isnan(result.advantage)
    assert math.isnan(result.spread_return_if_right)
    assert f"{result.single_return_if_right:.2f}x" in result.reason


def test_straddles_count_as_singles_only_for_a_move() -> None:
    dist = _closed_dist()
    straddle = build(K.LONG_STRADDLE, [100.0], [2.0, 2.0], YEARS)
    for view, expected in (
        (View(85.0, 115.0, outside=True), K.LONG_STRADDLE),
        (View(110.0, None), None),
    ):
        scores = score_structures([straddle], dist, view)
        result = verdict(best_per_kind(scores, min_prob_profit_given_view=0.0), view)
        assert result.best_single_kind == expected
        assert result.best_kind == K.LONG_STRADDLE


@pytest.mark.parametrize("template_id", sorted(REASON_TEMPLATES))
def test_templates_never_advise(template_id: str) -> None:
    words = re.findall(r"[a-z]+", REASON_TEMPLATES[template_id].lower())
    for banned in BANNED:
        assert not any(word.startswith(banned) for word in words), (template_id, banned)
