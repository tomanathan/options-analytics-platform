"""Enumerate option structures from one expiration's chain, and compare them for an outcome.

``enumerate_structures`` lists every structure of ``oap.engine.positions.StructureKind`` that
the usable quotes allow, at natural or mid fills. ``best_per_kind`` keeps the structure of each
kind with the highest return if the outcome happens, ``dominance`` says which kind pays the most
per dollar of max loss at each terminal price, and ``verdict`` compares the best spread with the
best outright long premium in one descriptive sentence.

The sentences describe which structure serves an outcome under the calibrated distribution;
they never advise a trade.

Units: strikes and prices in dollars per share; returns on max loss as decimals (1.5 is
"1.50x on risk"); probabilities as decimals in [0, 1].
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import numpy.typing as npt

from oap.engine._types import FloatArray
from oap.engine._validation import (
    as_float_1d,
    require_finite_scalar,
    require_non_negative,
    require_positive,
    require_same_length,
    require_strictly_increasing,
)
from oap.engine.errors import EngineInputError
from oap.engine.positions import (
    KIND_SPECS,
    Position,
    StructureKind,
    StructureScore,
    View,
    build,
)

Fill = Literal["natural", "mid"]
"""natural: long legs at the ask and short legs at the bid; mid: every leg at the mid."""

STRADDLE_MAX_MONEYNESS: Final = 0.10
"""Straddle strikes lie within this fraction of the close (|K / close - 1| <= 0.10)."""
TIE_TOLERANCE: Final = 0.05
"""Returns on max loss closer than this (a decimal) are reported as about the same."""
_WIDTH_DECIMALS: Final = 6  # condor wings are matched on widths rounded to 1e-6 dollars

SPREAD_KINDS: Final = frozenset(
    {
        StructureKind.BULL_CALL_SPREAD,
        StructureKind.BEAR_PUT_SPREAD,
        StructureKind.BULL_PUT_SPREAD,
        StructureKind.BEAR_CALL_SPREAD,
        StructureKind.IRON_CONDOR,
    }
)
"""Spreads: the four verticals and the iron condor."""
SINGLE_KINDS: Final = frozenset({StructureKind.LONG_CALL, StructureKind.LONG_PUT})
"""Outright long premium; the straddle and strangle join them when the outcome is a move."""
MOVE_SINGLE_KINDS: Final = frozenset({StructureKind.LONG_STRADDLE, StructureKind.LONG_STRANGLE})

KIND_LABELS: Final[Mapping[StructureKind, str]] = {
    kind: kind.value.replace("_", " ") for kind in StructureKind
}
"""Human-readable kind names, such as ``bull call spread``."""

REASON_TEMPLATES: Final[Mapping[str, str]] = {
    "none": "No structure kind qualifies for this outcome, so there is nothing to compare.",
    "no_spread": (
        "No spread qualifies for this outcome; the {single} returns {single_r} on risk if the "
        "outcome happens."
    ),
    "no_single": (
        "No outright long option qualifies for this outcome; the {spread} returns {spread_r} "
        "on risk if the outcome happens."
    ),
    "tie": (
        "The {spread} and the {single} return about the same on risk inside this outcome: "
        "{spread_r} against {single_r}."
    ),
    "spread_capped_above": (
        "The outcome is bounded above at {hi}, so the long call's payoff beyond it is never "
        "collected; the {spread} returns {spread_r} on risk against {single_r}."
    ),
    "spread_capped_below": (
        "The outcome is bounded below at {lo}, so the long put's payoff below it is never "
        "collected; the {spread} returns {spread_r} on risk against {single_r}."
    ),
    "spread_cheaper": (
        "Capping the payoff lowers the capital at risk by more than it lowers the payoff "
        "inside this outcome, so the {spread} returns {spread_r} on risk against {single_r} "
        "for the {single}."
    ),
    "single_open_above": (
        "The outcome is open above {lo}, so the long call's unbounded payoff outweighs the "
        "spread's cheaper entry: {single_r} on risk against {spread_r} for the {spread}."
    ),
    "single_open_below": (
        "The outcome is open below {hi}, so the long put's payoff all the way down outweighs "
        "the spread's cheaper entry: {single_r} on risk against {spread_r} for the {spread}."
    ),
    "single_move": (
        "The outcome is a move outside {lo} to {hi}, so the {single}'s open-ended payoff "
        "outweighs the capped spread: {single_r} on risk against {spread_r} for the {spread}."
    ),
    "single_uncapped": (
        "The {single} returns {single_r} on risk against {spread_r} for the {spread}: inside "
        "this outcome the payoff the spread gives up is worth more than its cheaper entry."
    ),
}
"""The fixed sentences of ``verdict``; placeholders are filled with names and numbers."""


@dataclass(frozen=True, eq=False)
class ChainSide:
    """One right of one expiration's chain: usable quotes only, strikes ascending.

    Attributes:
        strikes: Strikes in dollars, positive and strictly increasing (may be empty).
        bids: Bids in dollars per share, finite and non-negative.
        asks: Asks in dollars per share, finite and at least the bid.
    """

    strikes: FloatArray
    bids: FloatArray
    asks: FloatArray

    def __post_init__(self) -> None:
        """Validate and freeze the arrays (dollars, dollars per share).

        Raises:
            EngineInputError: If the arrays differ in length, a strike is not positive, the
                strikes are not strictly increasing, or a quote is negative or crossed.
        """
        strikes = as_float_1d(self.strikes, "strikes", min_len=0)
        bids = as_float_1d(self.bids, "bids", min_len=0)
        asks = as_float_1d(self.asks, "asks", min_len=0)
        require_same_length(strikes, bids, ("strikes", "bids"))
        require_same_length(strikes, asks, ("strikes", "asks"))
        require_positive(strikes, "strikes")
        require_strictly_increasing(strikes, "strikes")
        require_non_negative(bids, "bids")
        if not np.all(asks >= bids):
            raise EngineInputError("asks must not be below bids")
        for arr in (strikes, bids, asks):
            arr.setflags(write=False)
        object.__setattr__(self, "strikes", strikes)
        object.__setattr__(self, "bids", bids)
        object.__setattr__(self, "asks", asks)

    def within(self, lo: float, hi: float) -> "ChainSide":
        """Keep the strikes in ``[lo, hi]``.

        Args:
            lo: Lowest strike kept, in dollars.
            hi: Highest strike kept, in dollars.

        Returns:
            The narrowed side.
        """
        keep = (self.strikes >= lo) & (self.strikes <= hi)
        return ChainSide(self.strikes[keep], self.bids[keep], self.asks[keep])

    def fills(self, fill: Fill) -> tuple[FloatArray, FloatArray]:
        """Return the fill price of a long and of a short leg at each strike.

        Args:
            fill: ``natural`` (long at the ask, short at the bid) or ``mid``.

        Returns:
            ``(long_prices, short_prices)`` in dollars per share.
        """
        if fill == "mid":
            mid = np.asarray(0.5 * (self.bids + self.asks), dtype=np.float64)
            return mid, mid
        return self.asks, self.bids


@dataclass(frozen=True, eq=False)
class _Candidates:
    """Structures of one kind as arrays, before the cap.

    Attributes:
        strikes: ``(n, n_strikes)`` distinct strikes in dollars, ascending per row.
        prices: ``(n, n_legs)`` fill prices in dollars per share, in template leg order.
        keys: Sort keys for the cap, most significant first, each of length ``n``.
    """

    strikes: FloatArray
    prices: FloatArray
    keys: tuple[FloatArray, ...]

    def keep(self, mask: npt.NDArray[np.bool_]) -> "_Candidates":
        """Return the rows where ``mask`` is true.

        Args:
            mask: Boolean row mask.

        Returns:
            The kept candidates.
        """
        return _Candidates(self.strikes[mask], self.prices[mask], tuple(k[mask] for k in self.keys))


def _pairs(side: ChainSide, max_width: float) -> tuple[npt.NDArray[np.intp], npt.NDArray[np.intp]]:
    """Return index pairs ``i < j`` of a side with ``strike[j] - strike[i] <= max_width``.

    Args:
        side: The chain side.
        max_width: Widest pair in dollars.

    Returns:
        ``(i, j)`` index arrays.
    """
    i, j = np.triu_indices(side.strikes.shape[0], 1)
    keep = side.strikes[j] - side.strikes[i] <= max_width
    return i[keep], j[keep]


def _verticals(
    calls: ChainSide, puts: ChainSide, fill: Fill, close: float, max_width: float
) -> dict[StructureKind, _Candidates]:
    """Build the four vertical spreads.

    Args:
        calls: Call side within the knots.
        puts: Put side within the knots.
        fill: The fill.
        close: Underlying close in dollars.
        max_width: Widest spread in dollars.

    Returns:
        Candidates per vertical kind, keyed for the cap by the distance of the strike nearest
        the close, then the width, then the lower strike.
    """
    out: dict[StructureKind, _Candidates] = {}
    for side, debit, credit in (
        (calls, StructureKind.BULL_CALL_SPREAD, StructureKind.BEAR_CALL_SPREAD),
        (puts, StructureKind.BEAR_PUT_SPREAD, StructureKind.BULL_PUT_SPREAD),
    ):
        long_px, short_px = side.fills(fill)
        i, j = _pairs(side, max_width)
        k1, k2 = side.strikes[i], side.strikes[j]
        strikes = np.stack([k1, k2], axis=1)
        keys = (np.minimum(np.abs(k1 - close), np.abs(k2 - close)), k2 - k1, k1)
        if side is calls:
            debit_prices = np.stack([long_px[i], short_px[j]], axis=1)  # +1 C K1, -1 C K2
            credit_prices = np.stack([short_px[i], long_px[j]], axis=1)  # -1 C K1, +1 C K2
        else:
            debit_prices = np.stack([long_px[j], short_px[i]], axis=1)  # +1 P K2, -1 P K1
            credit_prices = np.stack([short_px[j], long_px[i]], axis=1)  # -1 P K2, +1 P K1
        out[debit] = _Candidates(strikes, debit_prices, keys)
        out[credit] = _Candidates(strikes, credit_prices, keys)
    return out


def _singles(
    calls: ChainSide, puts: ChainSide, fill: Fill, close: float
) -> dict[StructureKind, _Candidates]:
    """Build long calls, long puts and straddles.

    Args:
        calls: Call side within the knots.
        puts: Put side within the knots.
        fill: The fill.
        close: Underlying close in dollars.

    Returns:
        Candidates keyed for the cap by the distance of the strike from the close.
    """
    call_long, _ = calls.fills(fill)
    put_long, _ = puts.fills(fill)
    common, ic, ip = np.intersect1d(calls.strikes, puts.strikes, return_indices=True)
    near = np.abs(common / close - 1.0) <= STRADDLE_MAX_MONEYNESS + 1e-12
    common, ic, ip = common[near], ic[near], ip[near]
    return {
        StructureKind.LONG_CALL: _Candidates(
            calls.strikes[:, None],
            call_long[:, None],
            (np.abs(calls.strikes - close), calls.strikes),
        ),
        StructureKind.LONG_PUT: _Candidates(
            puts.strikes[:, None], put_long[:, None], (np.abs(puts.strikes - close), puts.strikes)
        ),
        StructureKind.LONG_STRADDLE: _Candidates(
            common[:, None],
            np.stack([call_long[ic], put_long[ip]], axis=1),
            (np.abs(common - close), common),
        ),
    }


def _strangles(
    calls: ChainSide, puts: ChainSide, fill: Fill, close: float, max_moneyness: float
) -> _Candidates:
    """Build long strangles: a put below the close and a call above it.

    Args:
        calls: Call side within the knots.
        puts: Put side within the knots.
        fill: The fill.
        close: Underlying close in dollars.
        max_moneyness: Largest ``|K / close - 1|`` of either leg, a decimal.

    Returns:
        Candidates keyed for the cap by the farther leg's distance from the close, then the
        nearer leg's.
    """
    call_long, _ = calls.fills(fill)
    put_long, _ = puts.fills(fill)
    tol = 1e-12
    ip = np.flatnonzero(
        (puts.strikes < close) & (puts.strikes >= close * (1 - max_moneyness) - tol)
    )
    ic = np.flatnonzero(
        (calls.strikes > close) & (calls.strikes <= close * (1 + max_moneyness) + tol)
    )
    grid_p, grid_c = np.meshgrid(ip, ic, indexing="ij")
    gp, gc = grid_p.ravel(), grid_c.ravel()
    kp, kc = puts.strikes[gp], calls.strikes[gc]
    far = np.maximum(close - kp, kc - close)
    near = np.minimum(close - kp, kc - close)
    return _Candidates(
        np.stack([kp, kc], axis=1), np.stack([put_long[gp], call_long[gc]], axis=1), (far, near, kp)
    )


def _condors(
    calls: ChainSide, puts: ChainSide, fill: Fill, close: float, max_width: float
) -> _Candidates:
    """Build iron condors from a bull put spread below the close and a bear call spread above.

    Both wings have the same width (matched to 1e-6 dollars) within the width cap.

    Args:
        calls: Call side within the knots.
        puts: Put side within the knots.
        fill: The fill.
        close: Underlying close in dollars.
        max_width: Widest wing in dollars.

    Returns:
        Candidates keyed for the cap by the short strike farther from the close (short
        strikes nearest the close first), then the width, then the short put strike.
    """
    put_long, put_short = puts.fills(fill)
    call_long, call_short = calls.fills(fill)
    pi, pj = _pairs(puts, max_width)
    put_ok = puts.strikes[pj] < close  # short put K2 below the close
    pi, pj = pi[put_ok], pj[put_ok]
    ci, cj = _pairs(calls, max_width)
    call_ok = calls.strikes[ci] > close  # short call K1 above the close
    ci, cj = ci[call_ok], cj[call_ok]
    put_w = np.round(puts.strikes[pj] - puts.strikes[pi], _WIDTH_DECIMALS)
    call_w = np.round(calls.strikes[cj] - calls.strikes[ci], _WIDTH_DECIMALS)
    rows_p: list[npt.NDArray[np.intp]] = []
    rows_c: list[npt.NDArray[np.intp]] = []
    for width in np.intersect1d(put_w, call_w):
        gp, gc = np.meshgrid(
            np.flatnonzero(put_w == width), np.flatnonzero(call_w == width), indexing="ij"
        )
        rows_p.append(gp.ravel())
        rows_c.append(gc.ravel())
    p = np.concatenate(rows_p) if rows_p else np.zeros(0, dtype=np.intp)
    c = np.concatenate(rows_c) if rows_c else np.zeros(0, dtype=np.intp)
    kp1, kp2 = puts.strikes[pi[p]], puts.strikes[pj[p]]
    kc1, kc2 = calls.strikes[ci[c]], calls.strikes[cj[c]]
    strikes = np.stack([kp1, kp2, kc1, kc2], axis=1)
    prices = np.stack(
        [put_short[pj[p]], put_long[pi[p]], call_short[ci[c]], call_long[cj[c]]], axis=1
    )
    far = np.maximum(close - kp2, kc1 - close)
    return _Candidates(strikes, prices, (far, kp2 - kp1, kp2))


def _valid(
    kind: StructureKind, cands: _Candidates, min_risk_fraction: float
) -> npt.NDArray[np.bool_]:
    """Flag the candidates that are structures: every leg filled and the premium sign right.

    A leg whose fill is 0 is skipped (the structure is dropped). Debit structures need
    ``net_premium > 0`` and credit structures ``net_premium < 0`` (a free lunch is a bad
    quote); a credit structure also needs a max loss of at least ``min_risk_fraction`` of its
    width, so a credit that nearly equals the width (a wide or stale quote at the mid) does
    not pass as an almost riskless structure.

    Args:
        kind: The structure kind.
        cands: The candidates.
        min_risk_fraction: Smallest max loss of a credit structure as a fraction of its width.

    Returns:
        Boolean row mask.
    """
    spec = KIND_SPECS[kind]
    quantities = np.asarray([q for _, q, _ in spec.legs], dtype=np.float64)
    net = cands.prices @ quantities
    filled = np.all(cands.prices > 0, axis=1)
    if spec.premium == "debit":
        return np.asarray(filled & (net > 0), dtype=np.bool_)
    widths = cands.strikes[:, 1] - cands.strikes[:, 0]  # a vertical's width, a condor's wing
    max_loss = widths + net  # credit is -net
    return np.asarray(filled & (net < 0) & (max_loss >= min_risk_fraction * widths), dtype=np.bool_)


def _capped(cands: _Candidates, max_per_kind: int) -> _Candidates:
    """Order candidates by their keys and keep at most ``max_per_kind``.

    Args:
        cands: The candidates.
        max_per_kind: Most rows kept.

    Returns:
        The first rows by key, most significant key first.
    """
    order = np.lexsort(tuple(reversed(cands.keys)))[:max_per_kind]
    return _Candidates(
        cands.strikes[order], cands.prices[order], tuple(k[order] for k in cands.keys)
    )


def enumerate_structures(
    calls: ChainSide,
    puts: ChainSide,
    *,
    close: float,
    years: float,
    knot_lo: float,
    knot_hi: float,
    fill: Fill,
    max_width_fraction: float = 0.10,
    strangle_max_moneyness: float = 0.15,
    max_per_kind: int = 400,
    min_risk_fraction: float = 0.05,
) -> list[Position]:
    """List the structures one expiration's usable quotes allow.

    Every strike lies in ``[knot_lo, knot_hi]``, so no leg relies on the completed tails for
    its price. Long legs fill at the ask (``natural``) or the mid, short legs at the bid or the
    mid. Verticals use every strike pair of one right up to ``max_width_fraction * close``
    wide; straddles every strike quoted on both sides within 10% of the close; strangles a put
    strike below the close and a call strike above it, both within ``strangle_max_moneyness``
    of it; iron condors a bull put spread with its short strike below the close and a bear
    call spread with its short strike above it, of equal widths within the width cap. Debit
    structures with ``net_premium <= 0`` and credit structures with ``net_premium >= 0`` are
    dropped, as is a credit structure whose max loss is below ``min_risk_fraction`` of its
    width (a credit that nearly equals the width is a wide or stale quote, not a structure
    with almost no risk). When a kind has more than ``max_per_kind``
    structures, those whose strikes are nearest the close are kept: the singles and
    straddles by strike distance, verticals by the strike nearest the close, strangles and
    condors by the farther of their two inner strikes.

    Args:
        calls: Usable call quotes, strikes ascending.
        puts: Usable put quotes, strikes ascending.
        close: Underlying close in dollars, positive.
        years: Time to expiration in years (ACT/365), positive.
        knot_lo: Lowest CDF knot in dollars.
        knot_hi: Highest CDF knot in dollars.
        fill: ``natural`` or ``mid``.
        max_width_fraction: Widest vertical or condor wing as a fraction of the close.
        strangle_max_moneyness: Largest ``|K / close - 1|`` of a strangle leg, a decimal.
        max_per_kind: Most structures kept per kind, at least 1.
        min_risk_fraction: Smallest max loss of a credit structure as a fraction of its
            width, a decimal in [0, 1).

    Returns:
        Positions in kind order (``StructureKind``), each kind ordered by its cap key.

    Raises:
        EngineInputError: If ``close`` or ``years`` is not positive, ``knot_lo > knot_hi``,
            ``fill`` is unknown, a fraction is not positive, ``max_per_kind < 1`` or
            ``min_risk_fraction`` is outside [0, 1).
    """
    if require_finite_scalar(close, "close") <= 0:
        raise EngineInputError("close must be positive")
    if require_finite_scalar(years, "years") <= 0:
        raise EngineInputError("years must be positive")
    if require_finite_scalar(knot_lo, "knot_lo") > require_finite_scalar(knot_hi, "knot_hi"):
        raise EngineInputError("knot_lo must not exceed knot_hi")
    if fill not in ("natural", "mid"):
        raise EngineInputError("fill must be natural or mid")
    if not (max_width_fraction > 0 and strangle_max_moneyness > 0):
        raise EngineInputError("max_width_fraction and strangle_max_moneyness must be positive")
    if max_per_kind < 1:
        raise EngineInputError("max_per_kind must be at least 1")
    if not (0.0 <= min_risk_fraction < 1.0):
        raise EngineInputError("min_risk_fraction must lie in [0, 1)")
    c = calls.within(knot_lo, knot_hi)
    p = puts.within(knot_lo, knot_hi)
    max_width = max_width_fraction * close
    candidates: dict[StructureKind, _Candidates] = {
        **_singles(c, p, fill, close),
        **_verticals(c, p, fill, close, max_width),
        StructureKind.LONG_STRANGLE: _strangles(c, p, fill, close, strangle_max_moneyness),
        StructureKind.IRON_CONDOR: _condors(c, p, fill, close, max_width),
    }
    positions: list[Position] = []
    for kind in StructureKind:
        cands = candidates[kind]
        kept = _capped(cands.keep(_valid(kind, cands, min_risk_fraction)), max_per_kind)
        for strikes, prices in zip(kept.strikes, kept.prices, strict=True):
            positions.append(build(kind, strikes.tolist(), prices.tolist(), years))
    return positions


# -- comparison -----------------------------------------------------------------------------------


def qualifies(score: StructureScore, min_prob_profit_given_view: float) -> bool:
    """Say whether a score takes part in the comparison.

    Args:
        score: The score.
        min_prob_profit_given_view: Smallest ``P(pnl > 0 | S in view)``, a decimal.

    Returns:
        True when the conditional probability of profit is at least the threshold and the
        return if right is finite.
    """
    pop = score.prob_profit_given_view
    return (
        math.isfinite(pop)
        and pop >= min_prob_profit_given_view
        and math.isfinite(score.return_if_right)
    )


def rank_key(score: StructureScore) -> tuple[float, float, str]:
    """Return the ordering key of the comparison, best first.

    Args:
        score: The score.

    Returns:
        ``(-return_if_right, -expected_return, legs_text)``.
    """
    return (-score.return_if_right, -score.expected_return, score.position.legs_text)


def ranked(
    scores: Iterable[StructureScore], *, min_prob_profit_given_view: float = 0.5
) -> list[StructureScore]:
    """Return the qualifying scores, highest return if right first.

    Args:
        scores: Scores of any kinds.
        min_prob_profit_given_view: Smallest ``P(pnl > 0 | S in view)``, a decimal.

    Returns:
        The qualifying scores ordered by ``rank_key``.
    """
    return sorted((s for s in scores if qualifies(s, min_prob_profit_given_view)), key=rank_key)


def best_per_kind(
    scores: Iterable[StructureScore], *, min_prob_profit_given_view: float = 0.5
) -> dict[StructureKind, StructureScore]:
    """Keep, for each kind, the qualifying score with the highest return if right.

    Args:
        scores: Scores of any kinds against one view.
        min_prob_profit_given_view: Smallest ``P(pnl > 0 | S in view)``, a decimal.

    Returns:
        One score per kind that has a qualifying instance, in ``StructureKind`` order; ties
        go to the higher expected return, then the legs text.
    """
    best: dict[StructureKind, StructureScore] = {}
    for score in ranked(scores, min_prob_profit_given_view=min_prob_profit_given_view):
        best.setdefault(score.position.kind, score)
    return {kind: best[kind] for kind in StructureKind if kind in best}


def dominance(
    bests: Mapping[StructureKind, StructureScore], grid: npt.ArrayLike
) -> list[tuple[float, float, StructureKind]]:
    """Say which kind pays the most per dollar of max loss at each terminal price.

    Args:
        bests: The best score per kind.
        grid: Terminal prices in dollars, ascending.

    Returns:
        ``(from, to, kind)`` runs of consecutive grid prices with the same winner: ``from`` is
        the run's first grid price, ``to`` the next run's first (the last grid price for the
        last run). Ties go to the kind earlier in ``StructureKind`` order. Empty without kinds
        or prices.
    """
    prices = np.asarray(grid, dtype=np.float64)
    kinds = [kind for kind in StructureKind if kind in bests]
    if not kinds or prices.shape[0] == 0:
        return []
    returns = np.stack(
        [bests[k].position.pnl(prices) / bests[k].position.max_loss for k in kinds], axis=0
    )
    winner = np.argmax(returns, axis=0)
    starts = np.flatnonzero(np.concatenate([[True], winner[1:] != winner[:-1]]))
    segments: list[tuple[float, float, StructureKind]] = []
    for n, start in enumerate(starts):
        end = float(prices[starts[n + 1]]) if n + 1 < starts.shape[0] else float(prices[-1])
        segments.append((float(prices[start]), end, kinds[int(winner[start])]))
    return segments


@dataclass(frozen=True)
class Verdict:
    """The comparison of the best spread with the best outright long premium for an outcome.

    Attributes:
        best_kind: Kind with the highest return if right; None when nothing qualifies.
        best_spread_kind: Best of the four verticals and the condor; None when none qualifies.
        best_single_kind: Best of the long call and put (and, for a move, the straddle and
            strangle); None when none qualifies.
        spread_return_if_right: Its return if right (return on max loss), a decimal; nan
            without one.
        single_return_if_right: Its return if right, a decimal; nan without one.
        advantage: ``spread_return_if_right - single_return_if_right``; nan when a side is
            missing.
        reason: One descriptive sentence from ``REASON_TEMPLATES``.
    """

    best_kind: StructureKind | None
    best_spread_kind: StructureKind | None
    best_single_kind: StructureKind | None
    spread_return_if_right: float
    single_return_if_right: float
    advantage: float
    reason: str


def _best_of(
    bests: Mapping[StructureKind, StructureScore], kinds: Iterable[StructureKind]
) -> StructureScore | None:
    """Return the best score among some kinds.

    Args:
        bests: The best score per kind.
        kinds: Kinds to consider.

    Returns:
        The score first by ``rank_key``, or None.
    """
    found = [bests[k] for k in kinds if k in bests]
    return min(found, key=rank_key) if found else None


def _multiple(value: float) -> str:
    """Format a return on max loss as a multiple of the capital at risk, such as ``1.74x``."""
    return f"{value:.2f}x"


def _dollars(value: float | None) -> str:
    """Format a price, such as ``$201.00``."""
    return "" if value is None else f"${value:,.2f}"


def _reason_id(spread: StructureScore, single: StructureScore, view: View) -> str:
    """Choose the template that explains a comparison where both sides exist.

    Args:
        spread: The best spread.
        single: The best single.
        view: The outcome.

    Returns:
        A key of ``REASON_TEMPLATES``.
    """
    advantage = spread.return_if_right - single.return_if_right
    kind = single.position.kind
    if abs(advantage) < TIE_TOLERANCE:
        return "tie"
    if advantage > 0:
        if kind == StructureKind.LONG_CALL and not view.outside and view.hi is not None:
            return "spread_capped_above"
        if kind == StructureKind.LONG_PUT and not view.outside and view.lo is not None:
            return "spread_capped_below"
        return "spread_cheaper"
    if not view.outside:
        if kind == StructureKind.LONG_CALL and view.hi is None and view.lo is not None:
            return "single_open_above"
        if kind == StructureKind.LONG_PUT and view.lo is None and view.hi is not None:
            return "single_open_below"
    elif view.lo is not None and view.hi is not None:
        return "single_move"
    return "single_uncapped"


def verdict(bests: Mapping[StructureKind, StructureScore], view: View) -> Verdict:
    """Compare the best spread with the best outright long premium for an outcome.

    Spreads are the four verticals and the iron condor; singles are the long call and put,
    and also the straddle and strangle when the outcome is a move (``view.outside``), since
    they are outright long premium too. The sentence is chosen by fixed rules: about the same
    when the returns differ by less than ``TIE_TOLERANCE``; when the spread wins, the bound of
    the outcome that caps the single's payoff, or the cheaper capital at risk; when the single
    wins, the open side of the outcome, the move, or the uncapped payoff.

    Args:
        bests: The best qualifying score per kind (``best_per_kind``).
        view: The outcome.

    Returns:
        The verdict; returns are on max loss, decimals.
    """
    singles = SINGLE_KINDS | (MOVE_SINGLE_KINDS if view.outside else frozenset())
    best = _best_of(bests, StructureKind)
    spread = _best_of(bests, SPREAD_KINDS)
    single = _best_of(bests, singles)
    names = {
        "lo": _dollars(view.lo),
        "hi": _dollars(view.hi),
        "spread": "" if spread is None else KIND_LABELS[spread.position.kind],
        "single": "" if single is None else KIND_LABELS[single.position.kind],
        "spread_r": "" if spread is None else _multiple(spread.return_if_right),
        "single_r": "" if single is None else _multiple(single.return_if_right),
    }
    if spread is None and single is None:
        reason_id = "none"
    elif spread is None:
        reason_id = "no_spread"
    elif single is None:
        reason_id = "no_single"
    else:
        reason_id = _reason_id(spread, single, view)
    spread_r = math.nan if spread is None else spread.return_if_right
    single_r = math.nan if single is None else single.return_if_right
    return Verdict(
        best_kind=None if best is None else best.position.kind,
        best_spread_kind=None if spread is None else spread.position.kind,
        best_single_kind=None if single is None else single.position.kind,
        spread_return_if_right=spread_r,
        single_return_if_right=single_r,
        advantage=spread_r - single_r,
        reason=REASON_TEMPLATES[reason_id].format(**names),
    )
