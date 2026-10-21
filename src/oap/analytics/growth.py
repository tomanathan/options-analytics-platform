"""Growth-optimal sizing of single long calls and puts under the calibrated distribution.

For an option with premium ``a`` (the ask) and payoff ``X(S)`` at expiry, the return on
premium is ``R = X / a - 1``, which is at least -1. Holding a fraction ``f`` of capital in
it grows capital by ``1 + f R``, so the expected log growth is ``g(f) = E[log(1 + f R)]``,
defined for ``f <= 1``. ``g`` is concave with ``g(0) = 0`` and ``g'(0) = E[R]``: when
``E[R] <= 0`` the best fraction is ``f* = 0`` and ``g* = 0`` (the option is not worth
holding at any size); otherwise ``f*`` is found on ``[0, F_MAX]``.

Integration. ``g`` is integrated against a ``TailCompletedCdf`` (the calibrated or raw
risk-neutral CDF, completed with lognormal tails as the structures API completes it) by a
``Quadrature`` whose masses sum to 1. Inside the knots the edges are the CDF's knots and
every option strike, so each segment has a uniform density and ``u = 1 + f R`` is affine on
it; the segment's mean of ``log u`` is then exact, ``(U(u_b) - U(u_a)) / (u_b - u_a)`` with
``U(u) = u log u - u``, and needs one logarithm per edge. (A calibrated CDF has a few hundred
knots, so this is about eight times cheaper than an 8-point Gauss-Legendre rule per segment,
and exact rather than approximate.) Each tail is integrated in the lognormal's
standard-normal variable ``u`` (``x = location *
exp(-/+ s u - s**2 / 2)``, density proportional to ``phi(u)``) with ``TAIL_ORDER``
Gauss-Legendre nodes from the outer knot to the ``TAIL_PROB`` quantile (99.99% above, 0.01%
below); the masses are scaled to the exact tail mass of that range, and the remaining
``TAIL_PROB`` sits at the lognormal's conditional mean beyond the quantile, which makes the
expectation of every payoff (affine there) exact. The tests check ``g`` against a
20,000-point Monte Carlo.

Maximisation. ``g`` is evaluated on ``GRID_SIZE`` fractions evenly spaced on ``[0, F_MAX]``
for every option with a positive quadrature mean of ``R``, then the best grid cell's two
neighbours bracket a golden-section search. Concavity makes the bracket contain the maximum.

Scoring. ``score_expiration`` builds the distributions exactly as the structures API does
(``chain_cdf``, ``apply_calibration``, ``tail_sigmas``, ``TailCompletedCdf.complete``) and
scores each usable call and put whose strike lies inside the CDF knots as a one-leg
``Position`` filled at the ask, with ``score_structures`` for the probability of profit,
expected return, standard deviation and tail share. ``score_session`` does that for every
ok snapshot of one session with the walk-forward map of the trade date's year (and regime,
when the regime maps are chosen) and settles each option at its expiration's settlement
close.

Units: strikes, prices, premiums and payoffs in dollars per share; returns on premium as
decimals (0.10 is 10%); volatility as a decimal; time in years (ACT/365) or calendar days;
probabilities and fractions of capital as decimals; log growth in nats per holding period.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from oap.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, fold_map_id
from oap.analytics.regime_calibration import UNKNOWN, regime_map_id, regime_of
from oap.analytics.sample import (
    OUTCOME_COLUMNS,
    QUOTE_COLUMNS,
    SNAPSHOT_KEY,
    SnapshotStatus,
    chain_cdf,
    empty_frame,
    require_columns,
    usable_mask,
)
from oap.analytics.views import tail_sigmas
from oap.engine._types import BoolArray, FloatArray
from oap.engine.calibration import CalibrationMap, apply_calibration
from oap.engine.conventions import dte_years
from oap.engine.errors import EngineInputError
from oap.engine.positions import (
    EVERYTHING,
    PositionBook,
    StructureKind,
    TailCompletedCdf,
    build,
    score_structures,
)

F_MAX: Final = 0.25
"""Largest fraction of capital in one option, a decimal."""
GRID_SIZE: Final = 64
"""Fractions on the coarse grid of ``[0, F_MAX]``, both ends included."""
GOLDEN_ITERATIONS: Final = 20
"""Golden-section steps; the bracket of two grid cells shrinks to about 5e-7 of capital."""
TAIL_ORDER: Final = 16
"""Gauss-Legendre nodes per tail, in the tail's standard-normal variable."""
TAIL_PROB: Final = 1e-4
"""Probability beyond the integrated range of each tail (the 99.99% and 0.01% quantiles)."""
POOLED_SUFFIX: Final = "_pooled"
"""Suffix of the columns scored with the pooled map when the regime maps are chosen."""

QUOTE_IV_COLUMNS: Final[tuple[str, ...]] = (*QUOTE_COLUMNS, "source_iv")
FEATURE_COLUMNS: Final[tuple[str, ...]] = (
    "underlying",
    "trade_date",
    "ret_20",
    "iv_rank_120",
    "atm_iv_change_5",
)
MAP_CHOICES: Final[tuple[str, ...]] = ("pooled", "regime")
_FEATURES: Final[tuple[str, ...]] = ("ret_20", "iv_rank_120", "atm_iv_change_5")

OPTION_COLUMNS: Final[tuple[str, ...]] = (
    "right",
    "strike",
    "bid",
    "ask",
    "mid",
    "prob_profit",
    "expected_return",
    "edge_pct",
    "return_std",
    "kelly_fraction",
    "growth_rate",
    "prob_profit_market",
    "expected_return_market",
    "kelly_fraction_market",
    "growth_rate_market",
    "growth_gap",
    "tail_share",
)
"""Columns of ``score_expiration``, one row per option."""
VARIANT_COLUMNS: Final[tuple[str, ...]] = (
    "prob_profit",
    "expected_return",
    "kelly_fraction",
    "growth_rate",
    "growth_gap",
)
"""Columns that depend on the calibration map, repeated with ``POOLED_SUFFIX``."""

SCORED_COLUMNS: Final[tuple[str, ...]] = (
    "underlying",
    "trade_date",
    "expiration",
    "dte_days",
    "years",
    "fold",
    "regime",
    "map_id",
    "is_out_of_sample",
    "underlying_close",
    "moneyness",
    *OPTION_COLUMNS,
    "ret_20",
    "iv_rank_120",
    "atm_iv_change_5",
    "settlement_date",
    "settlement_close",
    "realised_payoff",
    "realised_return",
    "win",
)
"""Columns of a scored, settled option; ``_pooled`` columns follow when they are scored."""

_TAIL_NODES, _TAIL_WEIGHTS = np.polynomial.legendre.leggauss(TAIL_ORDER)
_INV_PHI: Final = (math.sqrt(5.0) - 1.0) / 2.0


# --- quadrature ------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Quadrature:
    """A discretisation of a tail-completed distribution for piecewise-affine payoffs.

    Inside the knots the distribution is a set of segments with uniform density; outside,
    a set of weighted nodes. Segment masses plus node masses sum to 1.

    Attributes:
        edges: Segment edges inside the knots, in dollars, strictly increasing: the CDF's
            knots plus every payoff kink between them.
        segment_masses: Probability of each segment ``[edges[j], edges[j + 1])``.
        nodes: Tail nodes in dollars (Gauss-Legendre on the transformed grid, plus one node
            for the mass beyond each ``TAIL_PROB`` quantile).
        masses: Probability of each tail node.
    """

    edges: FloatArray
    segment_masses: FloatArray
    nodes: FloatArray
    masses: FloatArray


@dataclass(frozen=True, eq=False)
class ReturnGrid:
    """Returns on premium of several options at a quadrature's edges and tail nodes.

    Attributes:
        at_edges: ``R`` at each edge, ``(n_options, len(edges))``; affine between edges.
        at_nodes: ``R`` at each tail node, ``(n_options, len(nodes))``.
    """

    at_edges: FloatArray
    at_nodes: FloatArray

    def take(self, rows: npt.NDArray[np.int64]) -> "ReturnGrid":
        """Return the grid of a subset of options."""
        return ReturnGrid(self.at_edges[rows], self.at_nodes[rows])


def _normal_cdf(x: float) -> float:
    """Return the standard normal CDF at ``x``."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _beyond_mean(dist: TailCompletedCdf, x: float, *, upper: bool) -> float:
    """Return ``E[S | S > x]`` (upper) or ``E[S | S < x]`` (lower) under the tail lognormal.

    With ``f`` the location and ``s = sigma * sqrt(t)``, ``d2 = (ln(f / x) - s**2 / 2) / s``
    and ``d1 = d2 + s``: ``f Phi(d1) / Phi(d2)`` above and ``f Phi(-d1) / Phi(-d2)`` below.
    A payoff that is affine beyond ``x`` has its exact conditional mean there.

    Args:
        dist: The distribution.
        x: Price in dollars beyond the outer knot on the tail's side.
        upper: True for the tail above the highest knot.

    Returns:
        The conditional mean in dollars, or ``x`` when the probability underflows.
    """
    s = (dist.sigma_hi if upper else dist.sigma_lo) * math.sqrt(dist.years)
    d2 = (math.log(dist.location / x) - 0.5 * s * s) / s
    sign = 1.0 if upper else -1.0
    probability = _normal_cdf(sign * d2)
    if probability <= 1e-300:
        return x
    return dist.location * _normal_cdf(sign * (d2 + s)) / probability


def _tail_nodes(dist: TailCompletedCdf, *, upper: bool) -> tuple[FloatArray, FloatArray]:
    """Return the nodes and masses of one tail, on the transformed grid.

    Between the outer knot and the ``TAIL_PROB`` quantile: ``TAIL_ORDER`` Gauss-Legendre
    nodes in the tail's standard-normal variable, with masses scaled to the exact mass of
    that range. Beyond the quantile (or for a whole tail lighter than ``TAIL_PROB``): one node
    at the conditional mean, so the expectation of any affine payoff is exact there.

    Args:
        dist: The distribution.
        upper: True for the tail above the highest knot.

    Returns:
        ``(nodes, masses)`` in dollars and probabilities; empty for a tail without mass.
    """
    m_lo, m_hi = dist.tail_mass()
    mass = m_hi if upper else m_lo
    knot = dist.k_hi if upper else dist.k_lo
    if mass <= 0.0:
        return np.zeros(0), np.zeros(0)
    cut = dist.quantile(1.0 - TAIL_PROB if upper else TAIL_PROB)
    inside = math.isfinite(cut) and (cut > knot if upper else 0.0 < cut < knot)
    if mass <= TAIL_PROB or not inside:
        return np.asarray([_beyond_mean(dist, knot, upper=upper)]), np.asarray([mass])
    s = (dist.sigma_hi if upper else dist.sigma_lo) * math.sqrt(dist.years)
    sign = -1.0 if upper else 1.0
    f = dist.location

    def to_u(x: float) -> float:
        """Return the tail's standard-normal variable at price ``x`` (-d2 below, d2 above)."""
        return sign * (math.log(x / f) + 0.5 * s * s) / s

    u_knot, u_cut = to_u(knot), to_u(cut)
    lo, hi = min(u_knot, u_cut), max(u_knot, u_cut)
    u = lo + (hi - lo) * (_TAIL_NODES + 1.0) / 2.0
    nodes = f * np.exp(sign * s * u - 0.5 * s * s)
    weights = _TAIL_WEIGHTS * np.exp(-0.5 * u * u)
    between = abs(float(np.diff(dist.prob_below_array(np.asarray([knot, cut])))[0]))
    if not float(weights.sum()) > 0.0:
        return np.asarray([_beyond_mean(dist, knot, upper=upper)]), np.asarray([mass])
    masses = weights / weights.sum() * between
    rest = _beyond_mean(dist, cut, upper=upper)
    return (
        np.asarray(np.append(nodes, rest), dtype=np.float64),
        np.asarray(np.append(masses, max(mass - between, 0.0)), dtype=np.float64),
    )


def build_quadrature(dist: TailCompletedCdf, kinks: npt.ArrayLike) -> Quadrature:
    """Discretise a tail-completed distribution for payoffs that bend at ``kinks``.

    Args:
        dist: The distribution of the price at expiry.
        kinks: Strikes in dollars; those inside the knots become segment edges, so every
            payoff is affine on every segment.

    Returns:
        The quadrature; its masses are rescaled to sum to exactly 1.
    """
    k = np.asarray(kinks, dtype=np.float64)
    inside = k[(k > dist.k_lo) & (k < dist.k_hi)]
    edges = np.unique(np.concatenate([dist.base.strikes, inside]))
    segment = np.maximum(np.diff(dist.base.prob_below_array(edges)), 0.0)
    lower = _tail_nodes(dist, upper=False)
    upper = _tail_nodes(dist, upper=True)
    nodes = np.concatenate([lower[0], upper[0]])
    masses = np.concatenate([lower[1], upper[1]])
    total = float(segment.sum() + masses.sum())
    return Quadrature(
        edges=np.asarray(edges, dtype=np.float64),
        segment_masses=np.asarray(segment / total, dtype=np.float64),
        nodes=np.asarray(nodes, dtype=np.float64),
        masses=np.asarray(masses / total, dtype=np.float64),
    )


# --- growth ----------------------------------------------------------------------------------


def option_returns(
    quad: Quadrature, strikes: FloatArray, premiums: FloatArray, is_call: BoolArray
) -> ReturnGrid:
    """Return each option's return on premium at the quadrature's edges and tail nodes.

    Args:
        quad: The quadrature.
        strikes: Strikes in dollars, one per option.
        premiums: Premiums paid (the ask) in dollars per share, positive.
        is_call: True for a call, False for a put.

    Returns:
        ``R = payoff / premium - 1`` (at least -1) at the edges and at the nodes.
    """

    def at(x: FloatArray) -> FloatArray:
        k = strikes[:, None]
        payoff = np.where(
            is_call[:, None], np.maximum(x[None, :] - k, 0.0), np.maximum(k - x[None, :], 0.0)
        )
        return np.asarray(payoff / premiums[:, None] - 1.0, dtype=np.float64)

    return ReturnGrid(at(quad.edges), at(quad.nodes))


def mean_return(quad: Quadrature, returns: ReturnGrid) -> FloatArray:
    """Return ``E[R]`` per option: segment midpoints (exact for affine ``R``) and tail nodes."""
    mid = (returns.at_edges[:, :-1] + returns.at_edges[:, 1:]) / 2.0
    return np.asarray(mid @ quad.segment_masses + returns.at_nodes @ quad.masses)


def _segment_log_means(u: FloatArray) -> FloatArray:
    """Return the mean of ``log u`` over each segment for ``u`` affine between edges.

    With ``U(u) = u log u - u`` the mean is ``(U(u_b) - U(u_a)) / (u_b - u_a)``; when the
    segment changes ``u`` by less than ``1e-6`` of its midpoint the expansion
    ``log m - (u_b - u_a)**2 / (24 m**2)`` about the midpoint ``m`` is used instead.

    Args:
        u: Positive values at the edges along the last axis.

    Returns:
        One mean per segment, shape ``u.shape[:-1] + (u.shape[-1] - 1,)``.
    """
    log_u = np.log(u)
    big_u = u * log_u - u
    du = np.diff(u, axis=-1)
    mid = (u[..., :-1] + u[..., 1:]) / 2.0
    small = np.abs(du) <= 1e-6 * mid
    exact = np.diff(big_u, axis=-1) / np.where(small, 1.0, du)
    approx = np.log(mid) - du * du / (24.0 * mid * mid)
    return np.asarray(np.where(small, approx, exact), dtype=np.float64)


def expected_log_growth(
    quad: Quadrature, returns: ReturnGrid, fractions: npt.ArrayLike
) -> FloatArray:
    """Return ``E[log(1 + f R)]`` per option.

    Inside the knots each segment's mean of ``log(1 + f R)`` is exact (uniform density,
    affine ``R``); the tails use the quadrature's nodes.

    Args:
        quad: The quadrature.
        returns: Returns of ``n`` options on it.
        fractions: Fractions of capital, decimals in ``[0, 1)``: shape ``(n,)`` for one per
            option or ``(n, k)`` for ``k`` per option.

    Returns:
        Expected log growth in nats per holding period, the shape of ``fractions``.
    """
    f = np.asarray(fractions, dtype=np.float64)[..., None]
    if f.ndim == 3:
        edges, nodes = returns.at_edges[:, None, :], returns.at_nodes[:, None, :]
    else:
        edges, nodes = returns.at_edges, returns.at_nodes
    inside = _segment_log_means(1.0 + f * edges) @ quad.segment_masses
    tails = np.log1p(f * nodes) @ quad.masses
    return np.asarray(inside + tails, dtype=np.float64)


def growth_optimum(
    quad: Quadrature,
    returns: ReturnGrid,
    *,
    f_max: float = F_MAX,
    grid_size: int = GRID_SIZE,
    iterations: int = GOLDEN_ITERATIONS,
) -> tuple[FloatArray, FloatArray]:
    """Return each option's growth-optimal fraction and its expected log growth.

    Options with ``E[R] <= 0`` under the quadrature get ``f* = 0`` and ``g* = 0``: ``g`` is
    concave with ``g'(0) = E[R]``. The others are evaluated on ``grid_size`` fractions
    evenly spaced on ``[0, f_max]``, and the best cell's neighbours bracket a golden-section
    search.

    Args:
        quad: The quadrature.
        returns: Returns of the options on it.
        f_max: Largest fraction, a decimal in ``(0, 1)``.
        grid_size: Fractions on the coarse grid, at least 2.
        iterations: Golden-section steps.

    Returns:
        ``(kelly_fraction, growth_rate)``: decimals in ``[0, f_max]`` and non-negative log
        growth in nats per holding period, one per option.

    Raises:
        ValueError: If ``f_max`` or ``grid_size`` is out of range.
    """
    if not 0.0 < f_max < 1.0:
        raise ValueError("f_max must be in (0, 1)")
    if grid_size < 2:
        raise ValueError("grid_size must be at least 2")
    n = returns.at_edges.shape[0]
    kelly, growth = np.zeros(n), np.zeros(n)
    live = np.flatnonzero(mean_return(quad, returns) > 0.0)
    if live.shape[0] == 0:
        return kelly, growth
    r = returns.take(live)
    rows = np.arange(live.shape[0])
    grid = np.linspace(0.0, f_max, grid_size)
    values = expected_log_growth(quad, r, np.broadcast_to(grid, (live.shape[0], grid_size)))
    values[:, 0] = 0.0
    best = np.argmax(values, axis=1)
    a = grid[np.maximum(best - 1, 0)]
    b = grid[np.minimum(best + 1, grid_size - 1)]
    c = b - _INV_PHI * (b - a)
    d = a + _INV_PHI * (b - a)
    gc, gd = expected_log_growth(quad, r, c), expected_log_growth(quad, r, d)
    for _ in range(iterations):
        left = gc > gd
        b = np.where(left, d, b)
        a = np.where(left, a, c)
        c_new = np.where(left, b - _INV_PHI * (b - a), d)
        d_new = np.where(left, c, a + _INV_PHI * (b - a))
        value = expected_log_growth(quad, r, np.where(left, c_new, d_new))
        gc, gd = np.where(left, value, gd), np.where(left, gc, value)
        c, d = c_new, d_new
    f = (a + b) / 2.0
    g = expected_log_growth(quad, r, f)
    coarse = values[rows, best]
    use_grid = coarse > g
    f = np.where(use_grid, grid[best], f)
    g = np.where(use_grid, coarse, g)
    positive = g > 0.0
    kelly[live] = np.where(positive, f, 0.0)
    growth[live] = np.where(positive, g, 0.0)
    return kelly, growth


# --- one expiration --------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionBook:
    """The usable options of one expiration that are scored.

    Attributes:
        is_call: True for a call.
        strikes: Strikes in dollars.
        bids: Bids in dollars per share.
        asks: Asks in dollars per share, positive (the fill).
    """

    is_call: BoolArray
    strikes: FloatArray
    bids: FloatArray
    asks: FloatArray


def option_book(chain: pd.DataFrame, knot_lo: float, knot_hi: float) -> OptionBook:
    """Select the usable calls and puts with a positive ask and a strike inside the knots.

    Args:
        chain: Quote rows of one expiration with ``strike`` (dollars), ``option_right``
            (C or P), ``bid`` and ``ask`` (dollars per share).
        knot_lo: Lowest CDF knot in dollars.
        knot_hi: Highest CDF knot in dollars.

    Returns:
        The options, calls first, strikes ascending within each right.
    """
    usable = usable_mask(chain["bid"], chain["ask"]).to_numpy(dtype=np.bool_)
    strikes = chain["strike"].to_numpy(dtype=np.float64)
    asks = chain["ask"].to_numpy(dtype=np.float64)
    keep = usable & (asks > 0.0) & (strikes >= knot_lo) & (strikes <= knot_hi)
    rows = chain.loc[keep]
    is_call = (rows["option_right"].astype(str) == "C").to_numpy(dtype=np.bool_)
    order = np.lexsort((rows["strike"].to_numpy(dtype=np.float64), ~is_call))
    return OptionBook(
        is_call=is_call[order],
        strikes=rows["strike"].to_numpy(dtype=np.float64)[order],
        bids=rows["bid"].to_numpy(dtype=np.float64)[order],
        asks=rows["ask"].to_numpy(dtype=np.float64)[order],
    )


def _breakeven_probability(dist: TailCompletedCdf, book: OptionBook) -> FloatArray:
    """Return ``P(R > 0)``: ``P(S > K + a)`` for a call, ``P(S < K - a)`` for a put."""
    breakeven = np.where(book.is_call, book.strikes + book.asks, book.strikes - book.asks)
    below = dist.prob_below_array(np.maximum(breakeven, 0.0))
    return np.asarray(np.where(book.is_call, 1.0 - below, below), dtype=np.float64)


def _growth_columns(
    dist: TailCompletedCdf, book: OptionBook, *, f_max: float
) -> tuple[FloatArray, FloatArray]:
    """Return ``(kelly_fraction, growth_rate)`` of every option under one distribution."""
    quad = build_quadrature(dist, book.strikes)
    returns = option_returns(quad, book.strikes, book.asks, book.is_call)
    return growth_optimum(quad, returns, f_max=f_max)


def score_expiration(
    chain: pd.DataFrame,
    *,
    trade_date: date,
    expiration: date,
    maps: Mapping[str, CalibrationMap],
    config: AnalyticsConfig = DEFAULT_CONFIG,
    f_max: float = F_MAX,
) -> pd.DataFrame | None:
    """Score every usable long call and put of one expiration at the ask.

    Args:
        chain: Quote rows of one snapshot, both rights, with ``strike`` (dollars),
            ``option_right``, ``bid`` and ``ask`` (dollars per share) and ``source_iv``
            (decimal).
        trade_date: Trade date.
        expiration: Expiration date, after the trade date.
        maps: Calibration maps keyed by column suffix: ``""`` for the chosen map, and
            optionally ``POOLED_SUFFIX`` for the pooled map scored alongside it.
        config: ``risk_free_apy`` for the CDF.
        f_max: Largest fraction of capital, a decimal.

    Returns:
        One row per option with ``OPTION_COLUMNS`` (and the map-dependent columns again with
        each extra suffix), or None when the chain has no CDF, no quote with a positive IV,
        or no option inside the knots. ``expected_return`` is ``E[R]`` (``edge_pct`` repeats
        it), ``return_std`` the standard deviation of ``R``, both on premium; probabilities
        are decimals; ``growth_rate`` is in nats per holding period.

    Raises:
        EngineInputError: If the engine rejects the chain (not caught, as in
            ``build_predictions``).
    """
    years = dte_years(trade_date, expiration)
    cdf = chain_cdf(chain, years=years, rate=config.risk_free_apy)
    if cdf is None:
        return None
    try:
        sigma_lo, sigma_hi = tail_sigmas(chain)
    except EngineInputError:
        return None
    book = option_book(chain, float(cdf.strikes[0]), float(cdf.strikes[-1]))
    if book.strikes.shape[0] == 0:
        return None
    positions = [
        build(
            StructureKind.LONG_CALL if call else StructureKind.LONG_PUT,
            [float(k)],
            [float(a)],
            cdf.years,
        )
        for call, k, a in zip(book.is_call, book.strikes, book.asks, strict=True)
    ]
    market = TailCompletedCdf.complete(cdf, sigma_lo, sigma_hi)
    market_e1 = PositionBook(tuple(positions)).moments(market, EVERYTHING).e1
    kelly_market, growth_market = _growth_columns(market, book, f_max=f_max)
    out: dict[str, object] = {
        "right": np.where(book.is_call, "call", "put").astype(object),
        "strike": book.strikes,
        "bid": book.bids,
        "ask": book.asks,
        "mid": (book.bids + book.asks) / 2.0,
    }
    for suffix, cmap in maps.items():
        dist = TailCompletedCdf.complete(apply_calibration(cdf, cmap), sigma_lo, sigma_hi)
        scores = score_structures(positions, dist, EVERYTHING)
        kelly, growth = _growth_columns(dist, book, f_max=f_max)
        expected = np.asarray([s.expected_return for s in scores], dtype=np.float64)
        out[f"prob_profit{suffix}"] = np.asarray([s.prob_profit for s in scores])
        out[f"expected_return{suffix}"] = expected
        out[f"kelly_fraction{suffix}"] = kelly
        out[f"growth_rate{suffix}"] = growth
        out[f"growth_gap{suffix}"] = growth - growth_market
        if suffix == "":
            out["edge_pct"] = expected
            out["return_std"] = np.asarray([s.pnl_std / s.position.max_loss for s in scores])
            out["tail_share"] = np.asarray([s.tail_share for s in scores])
    out["prob_profit_market"] = _breakeven_probability(market, book)
    out["expected_return_market"] = market_e1 / book.asks
    out["kelly_fraction_market"] = kelly_market
    out["growth_rate_market"] = growth_market
    extra = [f"{c}{s}" for s in maps if s for c in VARIANT_COLUMNS]
    return pd.DataFrame(out)[[*OPTION_COLUMNS, *extra]]


# --- one session -----------------------------------------------------------------------------


def session_map_id(year: int, regime: str, chosen: str) -> str:
    """Return the walk-forward map id an option of a trade date uses.

    Args:
        year: Calendar year of the trade date.
        regime: The underlying's regime on the trade date.
        chosen: ``pooled`` or ``regime``, the step-1 decision.

    Returns:
        ``fold_<year>`` for the pooled maps, ``regime_map_id(year, regime)`` otherwise.

    Raises:
        ValueError: If ``chosen`` is unknown.
    """
    if chosen not in MAP_CHOICES:
        raise ValueError(f"unknown map choice {chosen!r}")
    return fold_map_id(year) if chosen == "pooled" else regime_map_id(year, regime)


@dataclass(frozen=True)
class SessionScores:
    """The scored options of one session and what was skipped.

    Attributes:
        options: Rows with ``SCORED_COLUMNS`` (and the pooled columns when scored).
        snapshots: Ok snapshots of the session.
        skipped: Ok snapshots that yielded no option (no CDF, no positive IV, nothing inside
            the knots, or no map for the year).
    """

    options: pd.DataFrame
    snapshots: int
    skipped: int


def _session_features(features: pd.DataFrame, trade_date: pd.Timestamp) -> pd.DataFrame:
    """Return the session's feature rows keyed by underlying, with the regime label."""
    rows = features.loc[pd.to_datetime(features["trade_date"]) == trade_date]
    rows = rows.drop_duplicates("underlying").set_index("underlying")
    rows = rows[["ret_20", "iv_rank_120", "atm_iv_change_5"]].astype("float64")
    rows["regime"] = regime_of(rows)
    return rows


def _settle(frame: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Join the settlement close and compute the realised payoff and return on premium."""
    settled = outcomes[list(OUTCOME_COLUMNS)].drop_duplicates(["underlying", "expiration"])
    out = frame.merge(settled, on=["underlying", "expiration"], how="left", validate="many_to_one")
    close = out["settlement_close"].to_numpy(dtype=np.float64)
    strike = out["strike"].to_numpy(dtype=np.float64)
    is_call = (out["right"] == "call").to_numpy(dtype=np.bool_)
    payoff = np.where(is_call, np.maximum(close - strike, 0.0), np.maximum(strike - close, 0.0))
    out["realised_payoff"] = payoff
    out["realised_return"] = payoff / out["ask"].to_numpy(dtype=np.float64) - 1.0
    out["win"] = out["realised_return"].to_numpy(dtype=np.float64) > 0.0
    return out


def score_session(
    quotes: pd.DataFrame,
    snapshots: pd.DataFrame,
    outcomes: pd.DataFrame,
    features: pd.DataFrame,
    maps: Mapping[str, CalibrationMap],
    config: AnalyticsConfig = DEFAULT_CONFIG,
    *,
    chosen: str,
    f_max: float = F_MAX,
) -> SessionScores:
    """Score and settle every usable long call and put of one session's ok snapshots.

    Each underlying uses the walk-forward map of the trade date's year (``session_map_id``);
    when ``chosen`` is ``regime`` the pooled fold map is scored too, into the
    ``_pooled`` columns. An option is out of sample when the year is at least
    ``first_test_year`` and its map is not the identity.

    Args:
        quotes: Quote rows of one ``trade_date`` with ``QUOTE_IV_COLUMNS``.
        snapshots: ``calibration_snapshot`` rows with the snapshot key and ``status``.
        outcomes: ``fct_expiration_outcome`` rows with ``OUTCOME_COLUMNS``.
        features: Regime features with ``FEATURE_COLUMNS`` (any dates).
        maps: Calibration maps keyed by map id (pooled fold maps and, for ``regime``, the
            regime maps).
        config: Analytics parameters.
        chosen: ``pooled`` or ``regime``.
        f_max: Largest fraction of capital, a decimal.

    Returns:
        The scored options sorted by underlying, expiration, right and strike, settled at
        the settlement close (``realised_return`` on premium; ``win`` when it is positive).

    Raises:
        ValueError: If a column is missing, the quotes span several trade dates or
            ``chosen`` is unknown.
    """
    require_columns(quotes, QUOTE_IV_COLUMNS, "quotes")
    require_columns(snapshots, (*SNAPSHOT_KEY, "status"), "snapshots")
    require_columns(outcomes, OUTCOME_COLUMNS, "outcomes")
    require_columns(features, FEATURE_COLUMNS, "features")
    if chosen not in MAP_CHOICES:
        raise ValueError(f"unknown map choice {chosen!r}")
    columns = [*SCORED_COLUMNS, *(f"{c}{POOLED_SUFFIX}" for c in VARIANT_COLUMNS)]
    columns = columns if chosen == "regime" else list(SCORED_COLUMNS)
    if quotes.empty:
        return SessionScores(empty_frame(tuple(columns)), 0, 0)
    if quotes["trade_date"].nunique() > 1:
        raise ValueError("quotes must hold a single trade_date")
    key = list(SNAPSHOT_KEY)
    ok = snapshots.loc[snapshots["status"] == SnapshotStatus.OK.value, key].drop_duplicates()
    session = quotes.merge(ok, on=key, how="inner")
    trade_date = pd.Timestamp(quotes["trade_date"].iloc[0])
    year = trade_date.year
    feats = _session_features(features, trade_date)
    parts: list[pd.DataFrame] = []
    meta: list[dict[str, object]] = []
    n_snapshots = skipped = 0
    for (underlying, expiration), chain in session.groupby(["underlying", "expiration"], sort=True):
        n_snapshots += 1
        dte_days = int(chain["dte_days"].iloc[0])
        regime = str(feats["regime"].get(underlying, UNKNOWN))
        map_id = session_map_id(year, regime, chosen)
        scored_maps = {"": maps.get(map_id)}
        if chosen == "regime":
            scored_maps[POOLED_SUFFIX] = maps.get(fold_map_id(year))
        known = {k: v for k, v in scored_maps.items() if v is not None}
        if dte_days < config.min_dte_days or len(known) < len(scored_maps):
            skipped += 1
            continue
        expiry = pd.Timestamp(str(expiration))
        frame = score_expiration(
            chain,
            trade_date=trade_date.date(),
            expiration=expiry.date(),
            maps=known,
            config=config,
            f_max=f_max,
        )
        if frame is None:
            skipped += 1
            continue
        parts.append(frame)
        meta.append(
            {
                "underlying": underlying,
                "expiration": expiry,
                "dte_days": dte_days,
                "years": dte_years(trade_date.date(), expiry.date()),
                "regime": regime,
                "map_id": map_id,
                "is_out_of_sample": year >= config.first_test_year and not known[""].is_identity,
                "underlying_close": float(chain["underlying_close"].iloc[0]),
                **{n: float(feats[n].get(underlying, np.nan)) for n in _FEATURES},
            }
        )
    if not parts:
        return SessionScores(empty_frame(tuple(columns)), n_snapshots, skipped)
    options = pd.concat(parts, ignore_index=True)
    counts = np.asarray([len(p) for p in parts], dtype=np.int64)
    for name in meta[0]:
        options[name] = np.repeat(np.asarray([m[name] for m in meta], dtype=object), counts)
    options["trade_date"] = trade_date
    options["fold"] = year
    options = options.astype(
        {
            "expiration": "datetime64[ns]",
            "dte_days": "int64",
            "years": "float64",
            "is_out_of_sample": "bool",
            "underlying_close": "float64",
            **dict.fromkeys(_FEATURES, "float64"),
        }
    )
    options["moneyness"] = options["strike"] / options["underlying_close"]
    settled = _settle(options, outcomes)
    return SessionScores(settled[columns].reset_index(drop=True), n_snapshots, skipped)


def leaking_options(options: pd.DataFrame, map_table: pd.DataFrame) -> pd.DataFrame:
    """Return the scored options whose map was trained on an outcome unknown at the time.

    Args:
        options: Scored options with ``map_id`` and ``trade_date``.
        map_table: Map rows with ``map_id`` and ``train_max_expiration`` (the latest
            expiration among the training rows; null when there were none).

    Returns:
        The options whose map's latest training expiration is on or after their trade date,
        or whose map is not in the table; empty when the walk-forward rule held.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(options, ("map_id", "trade_date"), "options")
    require_columns(map_table, ("map_id", "train_max_expiration"), "map table")
    latest = map_table.drop_duplicates("map_id").set_index("map_id")["train_max_expiration"]
    known = options["map_id"].isin(latest.index)
    trained = pd.to_datetime(options["map_id"].map(latest))
    late = trained.notna() & (trained >= pd.to_datetime(options["trade_date"]))
    return options.loc[(~known) | late]
