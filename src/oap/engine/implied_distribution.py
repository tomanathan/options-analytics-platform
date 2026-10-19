"""Market-implied distribution of the underlying price at expiry.

Builds the risk-neutral cumulative distribution function (CDF) of the underlying price
at expiry from option mid prices, using the Breeden-Litzenberger result. For a put
struck at ``K`` with price ``P(K)`` in dollars per share and time to expiry in years,
``dP/dK = F(K) / g`` where ``F(K)`` is the risk-neutral probability that the price at
expiry is below ``K`` and ``g = (1 + rate) ** years`` is the growth factor at the decimal
APY ``rate``. The slope of a vertical put spread between adjacent strikes therefore gives
``F`` at the midpoint of the two strikes, and the second derivative gives the density.

Calls give the same information through ``F = 1 + g * dC/dK``. When both sides are
supplied, each knot uses the out-of-the-money option, which is the more reliable quote.

Raw slopes from noisy quotes are not always monotone or inside [0, 1]. They are repaired
with weighted isotonic regression (strike spacing in dollars is the weight) and clipped,
and ``QualityFlag`` members report what was repaired and which tails the quoted strikes
do not cover. Outside the outer knots the CDF is held flat, so uncovered tail mass is
left undistributed rather than invented. Calibration of this risk-neutral distribution
against realised outcomes since 2020 happens in ``oap.engine.calibration``.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np
import numpy.typing as npt

from oap.engine._isotonic import isotonic_non_decreasing
from oap.engine._types import FloatArray
from oap.engine._validation import (
    as_float_1d,
    require_finite_scalar,
    require_non_negative,
    require_positive,
    require_same_length,
    require_strictly_increasing,
)
from oap.engine.black_scholes import implied_forward
from oap.engine.errors import EngineInputError

TAIL_COVERAGE: Final = 0.05
SPARSE_KNOTS: Final = 8
MIN_PUT_STRIKES: Final = 4
_REPAIR_TOL: Final = 1e-12


class QualityFlag(StrEnum):
    """Quality annotations attached to a ``RiskNeutralCdf``."""

    NO_CALLS = "no_calls"
    FORWARD_UNKNOWN = "forward_unknown"
    MONOTONICITY_REPAIRED = "monotonicity_repaired"
    CLIPPED = "clipped"
    LEFT_TAIL_UNCOVERED = "left_tail_uncovered"
    RIGHT_TAIL_UNCOVERED = "right_tail_uncovered"
    SPARSE = "sparse"
    CALIBRATED = "calibrated"


@dataclass(frozen=True, eq=False)
class RiskNeutralCdf:
    """Piecewise-linear risk-neutral CDF of the underlying price at expiry.

    Attributes:
        strikes: Knot prices in dollars, strictly increasing.
        cdf: Probability that the price at expiry is below each knot, as decimals in
            [0, 1], non-decreasing.
        raw_cdf: The same quantity before isotonic repair and clipping.
        forward: Forward price of the underlying in dollars; nan if unknown.
        years: Time to expiry in years.
        rate: Risk-free APY as a decimal.
        n_quotes: Number of option quotes used.
        flags: Quality annotations.
    """

    strikes: FloatArray
    cdf: FloatArray
    raw_cdf: FloatArray
    forward: float
    years: float
    rate: float
    n_quotes: int
    flags: frozenset[QualityFlag]

    def __post_init__(self) -> None:
        """Validate shapes and invariants, then freeze the arrays.

        Strikes are in dollars and must be strictly increasing; ``cdf`` holds
        probabilities that must be non-decreasing within [0, 1] (tolerance 0); ``years``
        must be positive. Arrays are replaced by read-only copies.

        Raises:
            EngineInputError: If any invariant is violated.
        """
        strikes = as_float_1d(self.strikes, "strikes")
        cdf = as_float_1d(self.cdf, "cdf")
        raw = as_float_1d(self.raw_cdf, "raw_cdf")
        require_same_length(strikes, cdf, ("strikes", "cdf"))
        require_same_length(strikes, raw, ("strikes", "raw_cdf"))
        require_strictly_increasing(strikes, "strikes")
        if not (np.all(cdf >= 0.0) and np.all(cdf <= 1.0)):
            raise EngineInputError("cdf must lie in [0, 1]")
        if not np.all(np.diff(cdf) >= 0.0):
            raise EngineInputError("cdf must be non-decreasing")
        if np.isinf(self.forward):
            raise EngineInputError("forward must be finite or nan")
        require_finite_scalar(self.years, "years")
        if self.years <= 0:
            raise EngineInputError("years must be positive")
        if require_finite_scalar(self.rate, "rate") <= -1:
            raise EngineInputError("rate must be greater than -1")
        if not isinstance(self.n_quotes, int) or self.n_quotes < 0:
            raise EngineInputError("n_quotes must be a non-negative int")
        if not all(isinstance(f, QualityFlag) for f in self.flags):
            raise EngineInputError("flags must contain only QualityFlag members")
        for arr in (strikes, cdf, raw):
            arr.setflags(write=False)
        object.__setattr__(self, "strikes", strikes)
        object.__setattr__(self, "cdf", cdf)
        object.__setattr__(self, "raw_cdf", raw)
        object.__setattr__(self, "flags", frozenset(self.flags))

    def prob_below(self, k: float) -> float:
        """Return the risk-neutral probability that the price at expiry is below ``k``.

        Linear between knots and flat outside them: flat extrapolation leaves the
        uncovered tail mass undistributed, and the tail flags report it.

        Args:
            k: Price in dollars.

        Returns:
            Probability as a decimal in [0, 1].
        """
        return float(self.prob_below_array(k))

    def prob_below_array(self, k: npt.ArrayLike) -> FloatArray:
        """Return ``prob_below`` for an array of prices.

        Linear between knots and flat outside them: flat extrapolation leaves the
        uncovered tail mass undistributed, and the tail flags report it.

        Args:
            k: Prices in dollars.

        Returns:
            Probabilities as decimals in [0, 1], same shape as ``k``.
        """
        x = np.asarray(k, dtype=np.float64)
        return np.asarray(
            np.interp(x, self.strikes, self.cdf, left=self.cdf[0], right=self.cdf[-1]),
            dtype=np.float64,
        )

    def prob_between(self, lo: float, hi: float) -> float:
        """Return the probability that the price at expiry lies between two prices.

        Args:
            lo: Lower price in dollars.
            hi: Upper price in dollars; must be at least ``lo``.

        Returns:
            ``F(hi) - F(lo)`` as a decimal in [0, 1].

        Raises:
            EngineInputError: If ``lo > hi``.
        """
        if lo > hi:
            raise EngineInputError("lo must not exceed hi")
        return self.prob_below(hi) - self.prob_below(lo)

    def quantile(self, p: float) -> float:
        """Return the generalised inverse ``inf{k : F(k) >= p}`` on the knots.

        Args:
            p: Probability as a decimal in [0, 1].

        Returns:
            Price in dollars, interpolated linearly between knots and clamped to the
            outer knots.

        Raises:
            EngineInputError: If ``p`` is not finite or outside [0, 1].
        """
        if not (np.isfinite(p) and 0.0 <= p <= 1.0):
            raise EngineInputError("p must be a finite probability in [0, 1]")
        n = self.cdf.shape[0]
        i = int(np.searchsorted(self.cdf, p, side="left"))
        if i == 0:
            return float(self.strikes[0])
        if i == n:
            return float(self.strikes[-1])
        k0, k1 = self.strikes[i - 1], self.strikes[i]
        c0, c1 = self.cdf[i - 1], self.cdf[i]
        return float(k0 + (p - c0) * (k1 - k0) / (c1 - c0))

    def integrate_cdf(self, a: float, b: float) -> float:
        """Return the exact integral of the CDF from ``a`` to ``b``.

        Args:
            a: Lower price in dollars.
            b: Upper price in dollars; must be at least ``a``.

        Returns:
            ``integral of F(x) dx`` over [a, b], in dollars (probability times dollars).

        Raises:
            EngineInputError: If ``a > b`` or either is not finite.
        """
        lo = require_finite_scalar(a, "a")
        hi = require_finite_scalar(b, "b")
        if lo > hi:
            raise EngineInputError("a must not exceed b")
        inside = self.strikes[(self.strikes > lo) & (self.strikes < hi)]
        grid = np.unique(np.concatenate([np.array([lo, hi]), inside]))
        return float(np.trapezoid(self.prob_below_array(grid), grid))

    def expected_payoff_put_spread(self, k_short: float, k_long: float) -> float:
        """Return the expected expiry payoff of a long put spread, undiscounted.

        The payoff is ``max(k_short - S, 0) - max(k_long - S, 0)`` per share, which
        equals the integral of the CDF between the strikes.

        Args:
            k_short: Higher strike in dollars.
            k_long: Lower strike in dollars; must be below ``k_short``.

        Returns:
            Expected payoff in dollars per share at expiry (not discounted).

        Raises:
            EngineInputError: If ``k_long >= k_short``.
        """
        if not k_long < k_short:
            raise EngineInputError("k_long must be below k_short")
        return self.integrate_cdf(k_long, k_short)

    def density(self) -> tuple[FloatArray, FloatArray]:
        """Return the piecewise-constant density between knots.

        Returns:
            ``(midpoints, density)``: bin midpoints in dollars and probability per dollar
            of price (1 / dollars), never negative.
        """
        d_strike = np.diff(self.strikes)
        mid = self.strikes[:-1] + 0.5 * d_strike
        return mid, np.asarray(np.diff(self.cdf) / d_strike, dtype=np.float64)


def _validate_side(
    strikes: npt.ArrayLike, mids: npt.ArrayLike, side: str, min_len: int
) -> tuple[FloatArray, FloatArray]:
    """Validate one side of a chain.

    Args:
        strikes: Strikes in dollars, strictly increasing and positive.
        mids: Mid prices in dollars per share, finite and non-negative.
        side: "put" or "call", used in error messages.
        min_len: Minimum number of strikes.

    Returns:
        Validated float64 copies of strikes and mids.

    Raises:
        EngineInputError: If any precondition is violated.
    """
    k = as_float_1d(strikes, f"{side}_strikes", min_len=min_len)
    m = as_float_1d(mids, f"{side}_mids", min_len=min_len)
    require_same_length(k, m, (f"{side}_strikes", f"{side}_mids"))
    require_positive(k, f"{side}_strikes")
    require_strictly_increasing(k, f"{side}_strikes")
    require_non_negative(m, f"{side}_mids")
    return k, m


def _check_time_and_rate(years: float, rate: float) -> float:
    """Validate time and rate, and return the growth factor.

    Args:
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.

    Returns:
        ``(1 + rate) ** years``, dimensionless.

    Raises:
        EngineInputError: If either value is non-finite or out of range.
    """
    if require_finite_scalar(years, "years") <= 0:
        raise EngineInputError("years must be positive")
    if require_finite_scalar(rate, "rate") <= -1:
        raise EngineInputError("rate must be greater than -1")
    return float((1.0 + rate) ** years)


def implied_cdf(
    put_strikes: npt.ArrayLike,
    put_mids: npt.ArrayLike,
    *,
    years: float,
    rate: float,
    call_strikes: npt.ArrayLike | None = None,
    call_mids: npt.ArrayLike | None = None,
    forward: float | None = None,
) -> RiskNeutralCdf:
    """Build the risk-neutral CDF of the price at expiry from option mid prices.

    Each pair of adjacent strikes gives one knot at their midpoint. Put knots use
    ``F = g * dP/dK``; call knots use ``F = 1 + g * dC/dK``, with ``g = (1 + rate) **
    years``. Where both exist at the same price, the out-of-the-money option wins (puts
    at or below the forward, calls above it). Raw values are made non-decreasing with
    weighted isotonic regression, weighted by strike spacing, then clipped to [0, 1].

    Args:
        put_strikes: Put strikes in dollars, at least 4, positive, strictly increasing.
        put_mids: Put mid prices in dollars per share, finite and non-negative.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        call_strikes: Optional call strikes in dollars, at least 2; needs ``call_mids``.
        call_mids: Optional call mid prices in dollars per share.
        forward: Optional forward price in dollars. When omitted it is inferred from
            put-call parity at the strikes common to both sides, if any.

    Returns:
        The repaired CDF with quality flags describing repairs and tail coverage.

    Raises:
        EngineInputError: If any input violates its precondition, or only one of
            ``call_strikes`` and ``call_mids`` is given.
    """
    p_k, p_m = _validate_side(put_strikes, put_mids, "put", MIN_PUT_STRIKES)
    growth = _check_time_and_rate(years, rate)
    if (call_strikes is None) != (call_mids is None):
        raise EngineInputError("call_strikes and call_mids must be given together")
    if forward is not None and not (np.isfinite(forward) and forward > 0):
        raise EngineInputError("forward must be finite and positive")

    flags: set[QualityFlag] = set()
    d_put = np.diff(p_k)
    put_knot = p_k[:-1] + 0.5 * d_put
    put_cdf = growth * np.diff(p_m) / d_put
    knot, raw, weight = put_knot, put_cdf, d_put
    n_quotes = p_k.shape[0]
    fwd = float("nan") if forward is None else float(forward)

    if call_strikes is not None and call_mids is not None:
        c_k, c_m = _validate_side(call_strikes, call_mids, "call", 2)
        n_quotes += c_k.shape[0]
        d_call = np.diff(c_k)
        call_knot = c_k[:-1] + 0.5 * d_call
        call_cdf = 1.0 + growth * np.diff(c_m) / d_call
        if forward is None:
            _, in_puts, in_calls = np.intersect1d(p_k, c_k, return_indices=True)
            if in_puts.shape[0] > 0:
                fwd = implied_forward(
                    p_k[in_puts], c_m[in_calls], p_m[in_puts], years=years, rate=rate
                )
        if np.isnan(fwd):
            put_rank = np.zeros_like(put_knot)
            call_rank = np.ones_like(call_knot)
        else:
            put_rank = np.where(put_knot <= fwd, 0.0, 1.0)
            call_rank = np.where(call_knot > fwd, 0.0, 1.0)
        all_knot = np.concatenate([put_knot, call_knot])
        all_cdf = np.concatenate([put_cdf, call_cdf])
        all_weight = np.concatenate([d_put, d_call])
        all_rank = np.concatenate([put_rank, call_rank])
        order = np.lexsort((all_rank, all_knot))
        _, first = np.unique(all_knot[order], return_index=True)
        keep = order[first]
        knot, raw, weight = all_knot[keep], all_cdf[keep], all_weight[keep]
    else:
        flags.add(QualityFlag.NO_CALLS)
    if np.isnan(fwd):
        flags.add(QualityFlag.FORWARD_UNKNOWN)

    repaired = isotonic_non_decreasing(raw, weight)
    cdf = np.clip(repaired, 0.0, 1.0)
    if np.max(np.abs(repaired - raw)) > _REPAIR_TOL:
        flags.add(QualityFlag.MONOTONICITY_REPAIRED)
    if np.any(raw < 0.0) or np.any(raw > 1.0):
        flags.add(QualityFlag.CLIPPED)
    if cdf[0] > TAIL_COVERAGE:
        flags.add(QualityFlag.LEFT_TAIL_UNCOVERED)
    if cdf[-1] < 1.0 - TAIL_COVERAGE:
        flags.add(QualityFlag.RIGHT_TAIL_UNCOVERED)
    if knot.shape[0] < SPARSE_KNOTS:
        flags.add(QualityFlag.SPARSE)
    return RiskNeutralCdf(
        strikes=knot,
        cdf=cdf,
        raw_cdf=raw,
        forward=fwd,
        years=float(years),
        rate=float(rate),
        n_quotes=n_quotes,
        flags=frozenset(flags),
    )


def breeden_litzenberger_density(
    strikes: npt.ArrayLike, mids: npt.ArrayLike, *, years: float, rate: float
) -> tuple[FloatArray, FloatArray]:
    """Return the raw risk-neutral density from the second derivative of option prices.

    Works for calls or puts because both have the same second derivative in strike. The
    result is raw: it can be negative where the quotes contain arbitrage.

    Args:
        strikes: Strikes in dollars, at least 3, positive, strictly increasing.
        mids: Option mid prices in dollars per share, finite and non-negative.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.

    Returns:
        ``(strikes[1:-1], density)``: interior strikes in dollars and probability per
        dollar of price (1 / dollars), ``g * 2 * (s[i] - s[i-1]) / (K[i+1] - K[i-1])``
        with ``s`` the slope between adjacent strikes and ``g = (1 + rate) ** years``.

    Raises:
        EngineInputError: If any input violates its precondition.
    """
    k, m = _validate_side(strikes, mids, "option", 3)
    growth = _check_time_and_rate(years, rate)
    slope = np.diff(m) / np.diff(k)
    density = growth * 2.0 * (slope[1:] - slope[:-1]) / (k[2:] - k[:-2])
    return k[1:-1], np.asarray(density, dtype=np.float64)


def usable_quotes(
    strikes: npt.ArrayLike, bids: npt.ArrayLike, asks: npt.ArrayLike
) -> tuple[FloatArray, FloatArray]:
    """Drop unusable quotes and return strikes with mid prices.

    A row is dropped when the strike, bid or ask is not finite, when ``bid <= 0`` (a
    zero-bid mid overstates value), or when ``ask < bid`` (a crossed quote).

    Args:
        strikes: Strikes in dollars.
        bids: Bid prices in dollars per share, one per strike.
        asks: Ask prices in dollars per share, one per strike.

    Returns:
        ``(strikes, mids)``: kept strikes in dollars, sorted ascending, and
        ``(bid + ask) / 2`` in dollars per share.

    Raises:
        EngineInputError: If the inputs are not 1-D arrays of equal length, or two kept
            rows share a strike.
    """
    arrays = []
    for name, values in (("strikes", strikes), ("bids", bids), ("asks", asks)):
        try:
            arr = np.array(values, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise EngineInputError(f"{name} must be numeric") from exc
        if arr.ndim != 1:
            raise EngineInputError(f"{name} must be 1-D")
        arrays.append(arr)
    k, b, a = arrays
    require_same_length(k, b, ("strikes", "bids"))
    require_same_length(k, a, ("strikes", "asks"))
    keep = np.isfinite(k) & np.isfinite(b) & np.isfinite(a) & (b > 0) & (a >= b)
    k, b, a = k[keep], b[keep], a[keep]
    order = np.argsort(k, kind="stable")
    k, b, a = k[order], b[order], a[order]
    if k.shape[0] > 1 and not np.all(np.diff(k) > 0):
        raise EngineInputError("strikes must be unique")
    return k, np.asarray(0.5 * (b + a), dtype=np.float64)
