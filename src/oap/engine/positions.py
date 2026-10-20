"""Option positions of one to four legs and their profit and loss at expiry.

A ``Position`` is a structure on one expiration with a finite maximum loss: long calls and
puts, the four verticals, the long straddle and strangle, and the iron condor (see
``StructureKind``). Everything is per share, in dollars, at expiry and undiscounted.

Profit and loss is measured under a ``TailCompletedCdf``: the risk-neutral CDF of
``oap.engine.implied_distribution`` (raw or calibrated) inside its knots, completed outside
them with lognormal tails that carry exactly the mass the knots leave undistributed. The
completion matters because a long call's expected payoff depends on the price beyond the last
quoted strike, which the flat CDF ignores, while a spread's does not.

Units: strikes, prices, premiums and profit and loss in dollars per share; volatility as a
decimal (0.20, not 20%); time in years (ACT/365); probabilities as decimals in [0, 1];
returns on max loss as decimals.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from statistics import NormalDist
from typing import Final, Literal

import numpy as np
import numpy.typing as npt

from oap.engine._types import BoolArray, FloatArray, Right
from oap.engine._validation import (
    as_float_1d,
    require_finite_scalar,
    require_strictly_increasing,
)
from oap.engine.black_scholes import _norm_cdf, _norm_pdf
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import RiskNeutralCdf
from oap.engine.spread_scoring import _annualise

Direction = Literal["up", "down", "move", "range"]
Premium = Literal["debit", "credit"]

_YEARS_MATCH_TOL: Final = 1e-9
_STD_FLOOR: Final = 1e-9  # pnl_std <= _STD_FLOOR * max_loss is treated as 0
PROB_FLOOR: Final = 1e-12
"""A view probability at or below this is treated as 0 (and 1 minus it as 1)."""
TAIL_SHARE_EPS: Final = 1e-12
"""Dollars per share added to the denominator of ``tail_share``."""
_TINY: Final = 1e-300  # a tail normaliser below this has underflowed
_BATCH: Final = 512  # positions per block in the vectorised scoring
_STANDARD_NORMAL: Final = NormalDist()


class StructureKind(StrEnum):
    """The structure kinds, in the order of the spec table."""

    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_CALL_SPREAD = "bear_call_spread"
    LONG_STRADDLE = "long_straddle"
    LONG_STRANGLE = "long_strangle"
    IRON_CONDOR = "iron_condor"


@dataclass(frozen=True)
class KindSpec:
    """The template of one structure kind.

    Attributes:
        direction: The outcome the kind is built for.
        premium: ``debit`` when the net premium is paid, ``credit`` when received.
        legs: ``(right, quantity, strike index)`` per leg in table order; the index points
            into the kind's distinct strikes sorted ascending (K1 < K2 < ...).
        n_strikes: Number of distinct strikes.
    """

    direction: Direction
    premium: Premium
    legs: tuple[tuple[Right, int, int], ...]
    n_strikes: int


KIND_SPECS: Final[dict[StructureKind, KindSpec]] = {
    StructureKind.LONG_CALL: KindSpec("up", "debit", (("C", 1, 0),), 1),
    StructureKind.LONG_PUT: KindSpec("down", "debit", (("P", 1, 0),), 1),
    StructureKind.BULL_CALL_SPREAD: KindSpec("up", "debit", (("C", 1, 0), ("C", -1, 1)), 2),
    StructureKind.BEAR_PUT_SPREAD: KindSpec("down", "debit", (("P", 1, 1), ("P", -1, 0)), 2),
    StructureKind.BULL_PUT_SPREAD: KindSpec("up", "credit", (("P", -1, 1), ("P", 1, 0)), 2),
    StructureKind.BEAR_CALL_SPREAD: KindSpec("down", "credit", (("C", -1, 0), ("C", 1, 1)), 2),
    StructureKind.LONG_STRADDLE: KindSpec("move", "debit", (("C", 1, 0), ("P", 1, 0)), 1),
    StructureKind.LONG_STRANGLE: KindSpec("move", "debit", (("P", 1, 0), ("C", 1, 1)), 2),
    StructureKind.IRON_CONDOR: KindSpec(
        "range", "credit", (("P", -1, 1), ("P", 1, 0), ("C", -1, 2), ("C", 1, 3)), 4
    ),
}
"""Leg templates per kind, as in the spec table (legs per share, strikes ascending)."""


def format_strike(strike: float) -> str:
    """Format a strike without trailing zeros.

    Args:
        strike: Strike in dollars.

    Returns:
        At most three decimals, trailing zeros and point removed: ``250``, ``182.5``.
    """
    return f"{strike:.3f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class Leg:
    """One option leg of a position.

    Attributes:
        right: ``C`` for a call, ``P`` for a put.
        strike: Strike in dollars per share, positive.
        quantity: +1 long, -1 short.
        price: Fill price in dollars per share, non-negative.
    """

    right: Right
    strike: float
    quantity: int
    price: float

    def __post_init__(self) -> None:
        """Validate the leg (strike in dollars, price in dollars per share).

        Raises:
            EngineInputError: If the right is not C or P, the strike is not finite and
                positive, the quantity is not +1 or -1, or the price is not finite and
                non-negative.
        """
        if self.right not in ("C", "P"):
            raise EngineInputError("right must be C or P")
        if require_finite_scalar(self.strike, "strike") <= 0:
            raise EngineInputError("strike must be positive")
        if self.quantity not in (1, -1):
            raise EngineInputError("quantity must be +1 or -1")
        if require_finite_scalar(self.price, "price") < 0:
            raise EngineInputError("price must be non-negative")

    def intrinsic(self, s: FloatArray) -> FloatArray:
        """Return the leg's payoff per unit quantity at expiry.

        Args:
            s: Prices of the underlying at expiry in dollars.

        Returns:
            ``max(s - K, 0)`` for a call, ``max(K - s, 0)`` for a put, in dollars per share.
        """
        if self.right == "C":
            return np.maximum(s - self.strike, 0.0)
        return np.maximum(self.strike - s, 0.0)


@dataclass(frozen=True)
class Position:
    """A structure of one to four legs on one expiration, with a finite maximum loss.

    Every quantity is per share, in dollars, at expiry and undiscounted. Use ``build`` to
    construct one from strikes and fill prices.

    Attributes:
        kind: The structure kind; the legs must follow its template in ``KIND_SPECS``.
        legs: The legs, in the template order.
        years: Time to expiration in years (ACT/365), positive.
    """

    kind: StructureKind
    legs: tuple[Leg, ...]
    years: float

    def __post_init__(self) -> None:
        """Validate the legs against the kind's template and the finite, positive max loss.

        Raises:
            EngineInputError: If the legs do not match the template (rights, quantities,
                strike order), ``years`` is not finite and positive, or the maximum loss is
                not finite and positive.
        """
        spec = KIND_SPECS[StructureKind(self.kind)]
        if not 1 <= len(self.legs) <= 4 or len(self.legs) != len(spec.legs):
            raise EngineInputError(f"{self.kind} needs {len(spec.legs)} legs")
        if require_finite_scalar(self.years, "years") <= 0:
            raise EngineInputError("years must be positive")
        by_index: dict[int, float] = {}
        for leg, (right, quantity, index) in zip(self.legs, spec.legs, strict=True):
            if leg.right != right or leg.quantity != quantity:
                raise EngineInputError(f"{self.kind} legs must follow the template")
            if by_index.setdefault(index, leg.strike) != leg.strike:
                raise EngineInputError(f"{self.kind} legs must share their strikes")
        ordered = [by_index[i] for i in range(spec.n_strikes)]
        if any(b <= a for a, b in zip(ordered, ordered[1:], strict=False)):
            raise EngineInputError(f"{self.kind} strikes must be strictly increasing")
        loss = self.max_loss
        if not (math.isfinite(loss) and loss > 0):
            raise EngineInputError(f"{self.kind} must have a finite, positive max loss")

    @property
    def direction(self) -> Direction:
        """The outcome the kind is built for: up, down, move or range."""
        return KIND_SPECS[self.kind].direction

    @cached_property
    def net_premium(self) -> float:
        """``sum(quantity * price)`` in dollars per share: positive a debit, negative a credit."""
        return float(sum(leg.quantity * leg.price for leg in self.legs))

    def pnl(self, s: npt.ArrayLike) -> FloatArray:
        """Return profit and loss at expiry.

        Args:
            s: Prices of the underlying at expiry in dollars.

        Returns:
            ``sum(quantity * intrinsic) - net_premium`` in dollars per share, the shape of
            ``s``.
        """
        x = np.asarray(s, dtype=np.float64)
        total = np.full(x.shape, -self.net_premium, dtype=np.float64)
        for leg in self.legs:
            total += leg.quantity * leg.intrinsic(x)
        return total

    @cached_property
    def kinks(self) -> tuple[float, ...]:
        """Distinct strikes in dollars, ascending: where the profit and loss bends."""
        return tuple(sorted({leg.strike for leg in self.legs}))

    @cached_property
    def slopes(self) -> tuple[int, int]:
        """P&L slopes in dollars per dollar of price: ``(slope_left, slope_right)``.

        ``slope_left`` holds below the lowest strike (minus the net put quantity) and
        ``slope_right`` above the highest (the net call quantity).
        """
        left = -sum(leg.quantity for leg in self.legs if leg.right == "P")
        right = sum(leg.quantity for leg in self.legs if leg.right == "C")
        return left, right

    @cached_property
    def _corner_values(self) -> tuple[FloatArray, FloatArray]:
        """Prices ``[0, kinks...]`` in dollars and the profit and loss there."""
        points = np.asarray((0.0, *self.kinks), dtype=np.float64)
        return points, self.pnl(points)

    @cached_property
    def max_loss(self) -> float:
        """Largest loss at expiry in dollars per share, positive; inf when unbounded.

        Evaluated at a price of 0, at the kinks, and at the open upper end (unbounded when
        the slope there is negative). The price at expiry cannot go below 0, so the lower
        end is the value at 0.
        """
        if self.slopes[1] < 0:
            return math.inf
        return float(-np.min(self._corner_values[1]))

    @cached_property
    def max_gain(self) -> float:
        """Largest gain at expiry in dollars per share; inf when the upper slope is positive."""
        if self.slopes[1] > 0:
            return math.inf
        return float(np.max(self._corner_values[1]))

    @cached_property
    def breakevens(self) -> tuple[float, ...]:
        """Prices at expiry in dollars where profit and loss crosses zero, ascending.

        Found per piecewise-linear segment between 0 and the kinks, and on the open upper
        segment when its slope is non-zero; a kink where the profit and loss is exactly 0
        counts. Zero to four values for these kinds.
        """
        points, values = self._corner_values
        roots: set[float] = set()
        for a, b, va, vb in zip(points[:-1], points[1:], values[:-1], values[1:], strict=True):
            if va * vb < 0:
                roots.add(float(a - va * (b - a) / (vb - va)))
        for x, v in zip(points[1:], values[1:], strict=True):
            if v == 0:
                roots.add(float(x))
        slope = self.slopes[1]
        if slope != 0 and values[-1] * slope < 0:
            roots.add(float(points[-1] - values[-1] / slope))
        return tuple(sorted(roots))

    @cached_property
    def profit_intervals(self) -> tuple[tuple[float, float], ...]:
        """Open price intervals in dollars where profit and loss is positive, ascending.

        The breakevens split ``(0, inf)``; profit and loss has one sign on each piece, which
        is read at an interior point.
        """
        bounds = (0.0, *self.breakevens, math.inf)
        kept: list[tuple[float, float]] = []
        for a, b in zip(bounds[:-1], bounds[1:], strict=True):
            probe = (
                0.5 * (a + b) if math.isfinite(b) else (2.0 * a + 1.0 if a > 0 else self.kinks[0])
            )
            if float(self.pnl(np.asarray([probe]))[0]) > 0:
                kept.append((a, b))
        return tuple(kept)

    @property
    def legs_text(self) -> str:
        """Legs as text, such as ``-1 P 250 / +1 P 245`` (signed quantity, right, strike)."""
        return " / ".join(
            f"{leg.quantity:+d} {leg.right} {format_strike(leg.strike)}" for leg in self.legs
        )


def build(
    kind: StructureKind, strikes: Sequence[float], prices: Sequence[float], years: float
) -> Position:
    """Build a position from its distinct strikes and per-leg fill prices.

    Args:
        kind: The structure kind.
        strikes: The kind's distinct strikes in dollars, ascending (K1 < K2 < ...; one strike
            for the straddle and the singles, four for the condor).
        prices: Fill prices in dollars per share, one per leg in the template order of
            ``KIND_SPECS`` (for example the bull put spread is short K2, long K1).
        years: Time to expiration in years (ACT/365).

    Returns:
        The validated position.

    Raises:
        EngineInputError: If the counts do not match the template or the position is invalid.
    """
    spec = KIND_SPECS[kind]
    if len(strikes) != spec.n_strikes:
        raise EngineInputError(f"{kind} needs {spec.n_strikes} strikes")
    if len(prices) != len(spec.legs):
        raise EngineInputError(f"{kind} needs {len(spec.legs)} prices")
    legs = tuple(
        Leg(right, float(strikes[index]), quantity, float(price))
        for (right, quantity, index), price in zip(spec.legs, prices, strict=True)
    )
    return Position(kind, legs, float(years))


@dataclass(frozen=True)
class View:
    """An outcome for the price at expiry: ``[lo, hi)`` or, when ``outside``, its complement.

    Attributes:
        lo: Lower bound in dollars, inclusive; None for no lower bound.
        hi: Upper bound in dollars, exclusive; None for no upper bound.
        outside: True for the prices outside ``[lo, hi)`` (a big move).
    """

    lo: float | None
    hi: float | None
    outside: bool = False

    def __post_init__(self) -> None:
        """Validate the bounds (dollars).

        Raises:
            EngineInputError: If a bound is not finite and positive, ``lo >= hi``, or the
                view is ``outside`` with no bound (an empty set).
        """
        for name, value in (("lo", self.lo), ("hi", self.hi)):
            if value is not None and require_finite_scalar(value, name) <= 0:
                raise EngineInputError(f"{name} must be positive")
        if self.lo is not None and self.hi is not None and not self.lo < self.hi:
            raise EngineInputError("lo must be below hi")
        if self.outside and self.lo is None and self.hi is None:
            raise EngineInputError("an outside view needs at least one bound")

    @property
    def lo_or_zero(self) -> float:
        """The lower bound in dollars, 0 when open."""
        return 0.0 if self.lo is None else self.lo

    @property
    def hi_or_inf(self) -> float:
        """The upper bound in dollars, inf when open."""
        return math.inf if self.hi is None else self.hi

    def contains_segments(self, left: FloatArray, right: FloatArray) -> BoolArray:
        """Flag the price segments ``[left, right)`` that lie in the view.

        The view's finite bounds must be among the segment edges, so every segment is either
        wholly in the view or wholly outside it.

        Args:
            left: Left edges in dollars.
            right: Right edges in dollars (inf allowed).

        Returns:
            True where the segment lies in the view.
        """
        inside = (left >= self.lo_or_zero) & (right <= self.hi_or_inf)
        return np.asarray(~inside if self.outside else inside, dtype=np.bool_)

    def closure_contains(self, x: FloatArray) -> BoolArray:
        """Flag the prices that lie in the closure of the view.

        Args:
            x: Prices in dollars, non-negative.

        Returns:
            True where ``x`` is in the closed view (bounds included).
        """
        lo, hi = self.lo_or_zero, self.hi_or_inf
        if self.outside:
            below = x <= lo if self.lo is not None else np.zeros(x.shape, dtype=np.bool_)
            above = x >= hi if self.hi is not None else np.zeros(x.shape, dtype=np.bool_)
            return np.asarray(below | above, dtype=np.bool_)
        return np.asarray((x >= lo) & (x <= hi), dtype=np.bool_)


EVERYTHING: Final = View(None, None, False)
"""The view that holds every price."""


def _d2(x: FloatArray, location: float, s: float) -> FloatArray:
    """Return the lognormal ``d2(x) = (ln(f / x) - s**2 / 2) / s``.

    Args:
        x: Prices in dollars, non-negative; 0 gives +inf and inf gives -inf.
        location: Mean ``f`` of the lognormal in dollars.
        s: Log standard deviation ``sigma * sqrt(t)``, positive.

    Returns:
        Dimensionless quantiles.
    """
    with np.errstate(divide="ignore"):
        log_ratio = np.log(location) - np.log(x)
    return np.asarray((log_ratio - 0.5 * s * s) / s, dtype=np.float64)


@dataclass(frozen=True, eq=False)
class TailCompletedCdf:
    """A risk-neutral CDF completed outside its knots with scaled lognormal tails.

    With ``t = base.years``, ``f = location``, ``k_0`` and ``k_n`` the outer knots,
    ``m_lo = F(k_0)`` and ``m_hi = 1 - F(k_n)`` the undistributed masses, ``s = sigma *
    sqrt(t)``, ``d2(x) = (ln(f / x) - s**2 / 2) / s`` and ``d1 = d2 + s``, the lognormal
    with mean ``f`` has survival ``Q(x) = P(S > x) = Phi(d2(x))`` and CDF ``L(x) =
    Phi(-d2(x))``. Then:

    * inside ``[k_0, k_n]``, ``F`` is the base CDF (piecewise linear);
    * above ``k_n``, ``1 - F(x) = m_hi * Q_hi(x) / Q_hi(k_n)``;
    * below ``k_0``, ``F(x) = m_lo * L_lo(x) / L_lo(k_0)``.

    ``F`` is continuous at both knots, monotone, ``F(0) = 0`` and ``F(inf) = 1``; a tail with
    no mass contributes nothing. When ``Q_hi(k_n)`` (or ``L_lo(k_0)``) underflows, the tail
    is the limit of the formula: a point mass at the knot.

    Partial moments used by ``expect``, for the lognormal with mean ``f``:

    * ``integral from x to inf of dF = Phi(d2(x))``;
    * ``integral from x to inf of S dF = f * Phi(d1(x))``;
    * ``integral from x to inf of S**2 dF = f**2 * exp(s**2) * Phi(d1(x) + s)``;
    * from 0 to ``x``: ``Phi(-d2(x))``, ``f * Phi(-d1(x))`` and
      ``f**2 * exp(s**2) * Phi(-d1(x) - s)``.

    Over a tail segment ``[a, b)`` these differences, times ``m_hi / Q_hi(k_n)`` above or
    ``m_lo / L_lo(k_0)`` below, give ``M_n = integral of S**n dF`` for ``n = 0, 1, 2``.

    Attributes:
        base: The raw or calibrated risk-neutral CDF.
        sigma_lo: Volatility of the lower tail, a decimal, positive.
        sigma_hi: Volatility of the upper tail, a decimal, positive.
        location: Mean of the tail lognormals in dollars: ``base.forward``, or
            ``base.quantile(0.5)`` when the forward is unknown (see ``complete``).
    """

    base: RiskNeutralCdf
    sigma_lo: float
    sigma_hi: float
    location: float

    def __post_init__(self) -> None:
        """Validate the tail volatilities (decimals) and the location (dollars).

        Raises:
            EngineInputError: If a volatility or the location is not finite and positive.
        """
        for name, value in (
            ("sigma_lo", self.sigma_lo),
            ("sigma_hi", self.sigma_hi),
            ("location", self.location),
        ):
            if require_finite_scalar(value, name) <= 0:
                raise EngineInputError(f"{name} must be positive")

    @classmethod
    def complete(cls, base: RiskNeutralCdf, sigma_lo: float, sigma_hi: float) -> "TailCompletedCdf":
        """Complete a CDF, centring the tails on its forward or, without one, its median.

        Args:
            base: The raw or calibrated risk-neutral CDF.
            sigma_lo: Lower tail volatility, a decimal.
            sigma_hi: Upper tail volatility, a decimal.

        Returns:
            The completed distribution.
        """
        forward = base.forward
        location = forward if math.isfinite(forward) and forward > 0 else base.quantile(0.5)
        return cls(base, float(sigma_lo), float(sigma_hi), float(location))

    # -- tail constants ---------------------------------------------------------------

    @property
    def years(self) -> float:
        """Time to expiry in years."""
        return self.base.years

    @property
    def k_lo(self) -> float:
        """Lowest knot in dollars."""
        return float(self.base.strikes[0])

    @property
    def k_hi(self) -> float:
        """Highest knot in dollars."""
        return float(self.base.strikes[-1])

    @cached_property
    def _s_lo(self) -> float:
        return self.sigma_lo * math.sqrt(self.years)

    @cached_property
    def _s_hi(self) -> float:
        return self.sigma_hi * math.sqrt(self.years)

    @cached_property
    def _masses(self) -> tuple[float, float]:
        return float(self.base.cdf[0]), float(1.0 - self.base.cdf[-1])

    def tail_mass(self) -> tuple[float, float]:
        """Return the masses the knots leave undistributed.

        Returns:
            ``(m_lo, m_hi)``: probability below the lowest knot and above the highest, as
            decimals in [0, 1].
        """
        return self._masses

    def _lower(self, x: FloatArray) -> FloatArray:
        """Lognormal CDF ``L_lo(x) = Phi(-d2(x))`` of the lower tail."""
        return _norm_cdf(-_d2(x, self.location, self._s_lo))

    def _upper(self, x: FloatArray) -> FloatArray:
        """Lognormal survival ``Q_hi(x) = Phi(d2(x))`` of the upper tail."""
        return _norm_cdf(_d2(x, self.location, self._s_hi))

    @cached_property
    def _norms(self) -> tuple[float, float]:
        """``(L_lo(k_0), Q_hi(k_n))``: the normalisers of the two tails."""
        lo = float(self._lower(np.asarray([self.k_lo]))[0])
        hi = float(self._upper(np.asarray([self.k_hi]))[0])
        return lo, hi

    @cached_property
    def _weights(self) -> tuple[float, float]:
        """``(m_lo / L_lo(k_0), m_hi / Q_hi(k_n))``; 0 for an empty or underflowed tail."""
        m_lo, m_hi = self._masses
        n_lo, n_hi = self._norms
        w_lo = m_lo / n_lo if m_lo > 0 and n_lo > _TINY else 0.0
        w_hi = m_hi / n_hi if m_hi > 0 and n_hi > _TINY else 0.0
        return w_lo, w_hi

    # -- distribution -----------------------------------------------------------------

    def prob_below_array(self, x: npt.ArrayLike) -> FloatArray:
        """Return ``F(x) = P(S < x)`` for an array of prices.

        Args:
            x: Prices in dollars; 0 and below give 0, inf gives 1.

        Returns:
            Probabilities as decimals in [0, 1], the shape of ``x``.
        """
        arr = np.asarray(x, dtype=np.float64)
        out = np.asarray(
            self.base.prob_below_array(np.clip(arr, self.k_lo, self.k_hi)), dtype=np.float64
        )
        w_lo, w_hi = self._weights
        below = arr < self.k_lo
        if np.any(below):
            xs = np.maximum(arr[below], 0.0)
            out[below] = w_lo * self._lower(xs)
        above = arr > self.k_hi
        if np.any(above):
            out[above] = 1.0 - w_hi * self._upper(arr[above])
        return np.asarray(np.clip(out, 0.0, 1.0), dtype=np.float64)

    def prob_below(self, x: float) -> float:
        """Return ``P(S < x)``.

        Args:
            x: Price in dollars.

        Returns:
            Probability as a decimal in [0, 1].
        """
        return float(self.prob_below_array(np.asarray([x], dtype=np.float64))[0])

    def prob_between(self, lo: float | None, hi: float | None) -> float:
        """Return ``P(lo <= S < hi)``.

        Args:
            lo: Lower price in dollars; None for no lower bound.
            hi: Upper price in dollars; None for no upper bound.

        Returns:
            Probability as a decimal in [0, 1].

        Raises:
            EngineInputError: If both bounds are set and ``lo > hi``.
        """
        if lo is not None and hi is not None and lo > hi:
            raise EngineInputError("lo must not exceed hi")
        upper = 1.0 if hi is None else self.prob_below(hi)
        lower = 0.0 if lo is None else self.prob_below(lo)
        return max(0.0, upper - lower)

    def prob_view(self, view: View) -> float:
        """Return the probability of a view.

        Args:
            view: The outcome.

        Returns:
            ``P(S in view)`` as a decimal in [0, 1].
        """
        inside = self.prob_between(view.lo, view.hi)
        return max(0.0, 1.0 - inside) if view.outside else inside

    def quantile(self, p: float) -> float:
        """Return the generalised inverse ``inf{x : F(x) >= p}``.

        Searches the knots for ``m_lo < p < 1 - m_hi`` and inverts a tail analytically
        otherwise: below, ``x = f * exp(s * z - s**2 / 2)`` with ``z = Phi^-1(p * L_lo(k_0) /
        m_lo)``; above, ``x = f * exp(-s * z - s**2 / 2)`` with ``z = Phi^-1((1 - p) *
        Q_hi(k_n) / m_hi)``.

        Args:
            p: Probability as a decimal in [0, 1].

        Returns:
            Price in dollars; 0 for ``p = 0`` and inf for ``p = 1`` when the upper tail has
            mass.

        Raises:
            EngineInputError: If ``p`` is not finite or outside [0, 1].
        """
        if not (math.isfinite(p) and 0.0 <= p <= 1.0):
            raise EngineInputError("p must be a finite probability in [0, 1]")
        m_lo, m_hi = self._masses
        w_lo, w_hi = self._weights
        if p == 0.0:
            return 0.0
        if p < m_lo:
            if w_lo == 0.0:
                return self.k_lo
            z = _STANDARD_NORMAL.inv_cdf(p / w_lo)
            return self.location * math.exp(self._s_lo * z - 0.5 * self._s_lo**2)
        if p > 1.0 - m_hi:
            if p >= 1.0:
                return math.inf
            if w_hi == 0.0:
                return self.k_hi
            z = _STANDARD_NORMAL.inv_cdf((1.0 - p) / w_hi)
            return self.location * math.exp(-self._s_hi * z - 0.5 * self._s_hi**2)
        return self.base.quantile(p)

    def density_array(self, x: npt.ArrayLike) -> FloatArray:
        """Return the probability density at each price.

        Inside the knots the density of the knot interval ``[k_i, k_i+1)`` holding ``x``;
        outside, the scaled lognormal density ``w * phi(d2(x)) / (x * s)``.

        Args:
            x: Prices in dollars.

        Returns:
            Density in probability per dollar (1/$), the shape of ``x``.
        """
        arr = np.asarray(x, dtype=np.float64)
        knots = self.base.strikes
        slopes = np.diff(self.base.cdf) / np.diff(knots)
        index = np.clip(np.searchsorted(knots, arr, side="right") - 1, 0, slopes.shape[0] - 1)
        out = np.asarray(slopes[index], dtype=np.float64)
        w_lo, w_hi = self._weights
        for mask, weight, s in (
            (arr < self.k_lo, w_lo, self._s_lo),
            (arr >= self.k_hi, w_hi, self._s_hi),
        ):
            if np.any(mask):
                xs = arr[mask]
                positive = xs > 0
                values = np.zeros(xs.shape, dtype=np.float64)
                if np.any(positive):
                    xp = xs[positive]
                    values[positive] = weight * _norm_pdf(_d2(xp, self.location, s)) / (xp * s)
                out[mask] = values
        return out

    def coarsened(self, knots: npt.ArrayLike) -> "TailCompletedCdf":
        """Return the distribution with its base CDF re-knotted at coarser prices, for display.

        A calibrated CDF composed with an isotonic (step) map has hundreds of knots: flat
        runs and near-vertical jumps between knots a few millionths of a dollar apart. Its
        point density (``density_array``) is therefore either about 0 or a spike, which no
        chart can show. Evaluating the CDF at the raw CDF's knots and interpolating linearly
        between them gives the landscape's calibrated curve (``density_calibrated``): the
        same probability in every knot interval, spread evenly over it. The outer knots must
        be this distribution's, so the tail masses, volatilities and location are unchanged.
        Use it for the display grid and density only; expectations use the exact CDF.

        Args:
            knots: Prices in dollars, strictly increasing, whose first and last equal the
                outer knots of ``base`` (to 1e-9 dollars).

        Returns:
            The coarsened distribution.

        Raises:
            EngineInputError: If the knots are not increasing or miss an outer knot.
        """
        k = as_float_1d(knots, "knots", min_len=2)
        require_strictly_increasing(k, "knots")
        if abs(k[0] - self.k_lo) > 1e-9 or abs(k[-1] - self.k_hi) > 1e-9:
            raise EngineInputError("knots must start and end at the outer knots of the base")
        k[0], k[-1] = self.k_lo, self.k_hi
        values = np.maximum.accumulate(np.clip(self.base.prob_below_array(k), 0.0, 1.0))
        base = RiskNeutralCdf(
            strikes=k,
            cdf=values,
            raw_cdf=values,
            forward=self.base.forward,
            years=self.base.years,
            rate=self.base.rate,
            n_quotes=self.base.n_quotes,
            flags=self.base.flags,
        )
        return TailCompletedCdf(base, self.sigma_lo, self.sigma_hi, self.location)

    # -- moments ------------------------------------------------------------------------

    def segment_moments(self, edges: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Return the moments of the distribution on each segment, centred at its left edge.

        The segments are ``[e_j, e_j+1)`` for consecutive ``edges`` plus ``[e_last, inf)``.
        ``edges`` must start at 0, be strictly increasing and include both outer knots and
        every base knot in between, so each segment lies in one tail or one knot interval.
        For a segment ``[a, b)`` the moments are ``M0 = P(a <= S < b)``, ``C1 = E[(S - a)
        1{a <= S < b}]`` and ``C2 = E[(S - a)**2 1{a <= S < b}]``:

        * inside the knots the density is constant, so ``M0 = dF``, ``C1 = dF (b - a) / 2``
          and ``C2 = dF (b - a)**2 / 3``; for an affine profit and loss this equals Simpson's
          rule on the segment, which is exact for the quadratic ``pnl**2``;
        * in a tail they are the lognormal partial moments of the class docstring, scaled by
          the tail weight and centred: ``C1 = M1 - a M0``, ``C2 = M2 - 2 a M1 + a**2 M0``.

        Args:
            edges: Segment edges in dollars, as described.

        Returns:
            ``(M0, C1, C2)``: probabilities, dollars and square dollars, one per segment.
        """
        left = edges
        right = np.append(edges[1:], math.inf)
        n = left.shape[0]
        m0 = np.zeros(n)
        c1 = np.zeros(n)
        c2 = np.zeros(n)
        k_lo, k_hi = self.k_lo, self.k_hi
        inside = (left >= k_lo) & (right <= k_hi)
        if np.any(inside):
            a, b = left[inside], right[inside]
            d_f = self.base.prob_below_array(b) - self.base.prob_below_array(a)
            width = b - a
            m0[inside] = d_f
            c1[inside] = d_f * width / 2.0
            c2[inside] = d_f * width * width / 3.0
        w_lo, w_hi = self._weights
        m_lo, m_hi = self._masses
        n_lo, n_hi = self._norms
        lower = right <= k_lo
        if np.any(lower) and m_lo > 0:
            if n_lo > _TINY:
                self._fill_tail(m0, c1, c2, lower, left, right, w_lo, self._s_lo, upper_tail=False)
            else:
                last = int(np.flatnonzero(lower)[-1])
                gap = k_lo - left[last]
                m0[last], c1[last], c2[last] = m_lo, m_lo * gap, m_lo * gap * gap
        upper = left >= k_hi
        if np.any(upper) and m_hi > 0:
            if n_hi > _TINY:
                self._fill_tail(m0, c1, c2, upper, left, right, w_hi, self._s_hi, upper_tail=True)
            else:
                first = int(np.flatnonzero(upper)[0])
                m0[first] = m_hi
        return m0, c1, c2

    def _fill_tail(
        self,
        m0: FloatArray,
        c1: FloatArray,
        c2: FloatArray,
        mask: BoolArray,
        left: FloatArray,
        right: FloatArray,
        weight: float,
        s: float,
        *,
        upper_tail: bool,
    ) -> None:
        """Write the centred lognormal moments of the tail segments in place.

        Args:
            m0: Probabilities per segment, updated where ``mask``.
            c1: Centred first moments in dollars, updated where ``mask``.
            c2: Centred second moments in square dollars, updated where ``mask``.
            mask: The segments of this tail.
            left: Left edges in dollars.
            right: Right edges in dollars (inf allowed).
            weight: ``m / normaliser`` of the tail.
            s: Log standard deviation of the tail, ``sigma * sqrt(t)``.
            upper_tail: True for the tail above the highest knot.
        """
        f = self.location
        a, b = left[mask], right[mask]
        d2a, d2b = _d2(a, f, s), _d2(b, f, s)
        growth = f * f * math.exp(s * s)
        sign = 1.0 if upper_tail else -1.0
        # Upper: integral from x to inf; lower: integral from 0 to x. Segment = value(a) -
        # value(b) above and value(b) - value(a) below, so the sign flips both.
        p0 = sign * (_norm_cdf(sign * d2a) - _norm_cdf(sign * d2b))
        p1 = sign * f * (_norm_cdf(sign * (d2a + s)) - _norm_cdf(sign * (d2b + s)))
        p2 = sign * growth * (_norm_cdf(sign * (d2a + 2 * s)) - _norm_cdf(sign * (d2b + 2 * s)))
        p0, p1, p2 = weight * p0, weight * p1, weight * p2
        m0[mask] = np.maximum(p0, 0.0)
        c1[mask] = np.maximum(p1 - a * p0, 0.0)
        c2[mask] = np.maximum(p2 - 2.0 * a * p1 + a * a * p0, 0.0)

    def expect(
        self, position: Position, lo: float | None = None, hi: float | None = None
    ) -> tuple[float, float, float]:
        """Return the probability and the first two P&L moments over ``[lo, hi)``.

        Exact: on every segment between the knots, the position's kinks and the bounds the
        profit and loss is affine and the moments of ``segment_moments`` integrate it in
        closed form (Simpson's rule inside the knots, lognormal partial moments in the tails).

        Args:
            position: The position; its ``years`` must match the distribution's.
            lo: Lower price in dollars, inclusive; None for 0.
            hi: Upper price in dollars, exclusive; None for inf.

        Returns:
            ``(P, E1, E2)``: ``P(lo <= S < hi)``, ``E[pnl 1{...}]`` in dollars per share and
            ``E[pnl**2 1{...}]`` in square dollars per share.

        Raises:
            EngineInputError: If ``lo >= hi`` or the years differ.
        """
        view = View(lo, hi, False)
        book = PositionBook((position,))
        moments = book.moments(self, view)
        return moments.prob_view, float(moments.e1_view[0]), float(moments.e2_view[0])


@dataclass(frozen=True, eq=False)
class BookMoments:
    """Probabilities and P&L moments of a book of positions over one view.

    Attributes:
        prob_view: ``P(S in view)``, a decimal.
        prob_out: ``P(S not in view)``, a decimal, summed separately for precision.
        e1: ``E[pnl]`` per position in dollars per share.
        e2: ``E[pnl**2]`` per position in square dollars per share.
        e1_view: ``E[pnl 1{S in view}]`` per position in dollars per share.
        e2_view: ``E[pnl**2 1{S in view}]`` per position in square dollars per share.
        e1_tails: ``E[pnl 1{S outside the knots}]`` per position in dollars per share.
        worst_view: Lowest P&L over the closed view per position in dollars per share.
    """

    prob_view: float
    prob_out: float
    e1: FloatArray
    e2: FloatArray
    e1_view: FloatArray
    e2_view: FloatArray
    e1_tails: FloatArray
    worst_view: FloatArray


@dataclass(frozen=True, eq=False)
class PositionBook:
    """Positions laid out as arrays, so many are scored against one distribution at once.

    The math is that of ``TailCompletedCdf.expect``, evaluated as matrix operations over the
    union of every position's kinks, the knots and the view bounds.

    Attributes:
        positions: The positions; all must share ``years``.
    """

    positions: tuple[Position, ...]

    @cached_property
    def _legs(self) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
        """``(is_call, strike, quantity)`` as ``(n, 4)`` arrays and the net premiums."""
        n = len(self.positions)
        is_call = np.zeros((n, 4))
        strike = np.zeros((n, 4))
        quantity = np.zeros((n, 4))
        for i, position in enumerate(self.positions):
            for j, leg in enumerate(position.legs):
                is_call[i, j] = 1.0 if leg.right == "C" else 0.0
                strike[i, j] = leg.strike
                quantity[i, j] = leg.quantity
        premium = np.asarray([p.net_premium for p in self.positions], dtype=np.float64)
        return is_call, strike, quantity, premium

    @cached_property
    def max_loss(self) -> FloatArray:
        """Maximum loss per position in dollars per share."""
        return np.asarray([p.max_loss for p in self.positions], dtype=np.float64)

    @cached_property
    def slope_right(self) -> FloatArray:
        """P&L slope above the highest strike per position (dollars per dollar)."""
        return np.asarray([p.slopes[1] for p in self.positions], dtype=np.float64)

    @cached_property
    def kinks(self) -> FloatArray:
        """Every distinct strike of the book in dollars, ascending."""
        if not self.positions:
            return np.zeros(0)
        return np.unique(np.concatenate([np.asarray(p.kinks) for p in self.positions]))

    def pnl_matrix(self, s: npt.ArrayLike, rows: slice = slice(None)) -> FloatArray:
        """Return profit and loss of the positions at each price.

        Args:
            s: Prices at expiry in dollars, 1-D.
            rows: The positions to evaluate.

        Returns:
            ``(n, len(s))`` array in dollars per share.
        """
        x = np.asarray(s, dtype=np.float64)[None, :]
        is_call, strike, quantity, premium = (a[rows] for a in self._legs)
        total = np.repeat(-premium[:, None], x.shape[1], axis=1)
        for j in range(4):
            k = strike[:, j : j + 1]
            call = np.maximum(x - k, 0.0)
            put = np.maximum(k - x, 0.0)
            intrinsic = np.where(is_call[:, j : j + 1] > 0, call, put)
            total += quantity[:, j : j + 1] * intrinsic
        return np.asarray(total, dtype=np.float64)

    def _check_years(self, dist: TailCompletedCdf) -> None:
        """Require every position to expire at the distribution's horizon.

        Args:
            dist: The distribution.

        Raises:
            EngineInputError: If a position's ``years`` differs by more than 1e-9.
        """
        for position in self.positions:
            if abs(position.years - dist.years) > _YEARS_MATCH_TOL:
                raise EngineInputError("position.years and the distribution's years must match")

    def moments(self, dist: TailCompletedCdf, view: View) -> BookMoments:
        """Integrate every position's profit and loss against the distribution.

        Args:
            dist: The tail-completed distribution of the price at expiry.
            view: The outcome; its bounds become segment edges.

        Returns:
            The moments, unconditional, in the view and in the tails.

        Raises:
            EngineInputError: If a position's ``years`` differs from the distribution's.
        """
        self._check_years(dist)
        bounds = [b for b in (view.lo, view.hi) if b is not None]
        edges = np.unique(
            np.concatenate([np.zeros(1), dist.base.strikes, self.kinks, np.asarray(bounds)])
        )
        m0, c1, c2 = dist.segment_moments(edges)
        right_edges = np.append(edges[1:], math.inf)
        in_view = view.contains_segments(edges, right_edges)
        in_tails = (right_edges <= dist.k_lo) | (edges >= dist.k_hi)
        closure = view.closure_contains(edges)
        n = len(self.positions)
        e1, e2 = np.zeros(n), np.zeros(n)
        e1_view, e2_view = np.zeros(n), np.zeros(n)
        e1_tails, worst = np.zeros(n), np.zeros(n)
        widths = np.diff(edges)
        for start in range(0, n, _BATCH):
            rows = slice(start, min(n, start + _BATCH))
            p = self.pnl_matrix(edges, rows)
            beta = np.concatenate(
                [np.diff(p, axis=1) / widths, self.slope_right[rows, None]], axis=1
            )
            first = p * m0 + beta * c1
            second = p * p * m0 + 2.0 * p * beta * c1 + beta * beta * c2
            e1[rows] = first.sum(axis=1)
            e2[rows] = second.sum(axis=1)
            e1_view[rows] = first[:, in_view].sum(axis=1)
            e2_view[rows] = second[:, in_view].sum(axis=1)
            e1_tails[rows] = first[:, in_tails].sum(axis=1)
            worst[rows] = p[:, closure].min(axis=1)
        return BookMoments(
            prob_view=float(m0[in_view].sum()),
            prob_out=float(m0[~in_view].sum()),
            e1=e1,
            e2=e2,
            e1_view=e1_view,
            e2_view=e2_view,
            e1_tails=e1_tails,
            worst_view=worst,
        )

    def profit_probabilities(
        self, dist: TailCompletedCdf, view: View
    ) -> tuple[FloatArray, FloatArray]:
        """Return each position's probability of profit, overall and inside the view.

        The profit regions are the intervals between breakevens where profit and loss is
        positive (``Position.profit_intervals``), measured with the distribution's CDF.

        Args:
            dist: The tail-completed distribution.
            view: The outcome.

        Returns:
            ``(P(pnl > 0), P(pnl > 0 and S in view))`` per position, decimals.
        """
        owner: list[int] = []
        lefts: list[float] = []
        rights: list[float] = []
        for i, position in enumerate(self.positions):
            for left, right in position.profit_intervals:
                owner.append(i)
                lefts.append(left)
                rights.append(right)
        n = len(self.positions)
        if not owner:
            return np.zeros(n), np.zeros(n)
        a = np.asarray(lefts)
        b = np.asarray(rights)
        lo, hi = view.lo_or_zero, view.hi_or_inf
        a_in = np.maximum(a, lo)
        b_in = np.minimum(b, hi)
        values = dist.prob_below_array(np.concatenate([a, b, a_in, b_in]))
        f_a, f_b, f_ain, f_bin = np.split(values, 4)
        whole = np.maximum(f_b - f_a, 0.0)
        inside = np.where(b_in > a_in, np.maximum(f_bin - f_ain, 0.0), 0.0)
        in_view = np.maximum(whole - inside, 0.0) if view.outside else inside
        index = np.asarray(owner)
        return (
            np.bincount(index, weights=whole, minlength=n),
            np.bincount(index, weights=in_view, minlength=n),
        )


@dataclass(frozen=True)
class StructureScore:
    """A position scored against a distribution and a view.

    Profit and loss is per share at expiry, undiscounted, with no interest on the capital at
    risk; returns are on max loss (the capital at risk) as decimals.

    Attributes:
        position: The position.
        prob_profit: ``P(pnl > 0)``, unconditional.
        expected_pnl: ``E[pnl]`` in dollars per share.
        pnl_std: Standard deviation of profit and loss in dollars per share.
        expected_return: ``expected_pnl / max_loss`` over the holding period.
        annualised_return: ``expected_return`` compounded to one year, as in
            ``oap.engine.spread_scoring``.
        reward_to_risk: ``expected_pnl / pnl_std``, per trade; nan when the std is 0.
        prob_view: ``P(S in view)``.
        prob_profit_given_view: ``P(pnl > 0 | S in view)``; nan when ``prob_view`` is 0.
        return_if_right: ``E[pnl | S in view] / max_loss``; nan when ``prob_view`` is 0.
        return_if_wrong: ``E[pnl | S not in view] / max_loss``; nan when ``prob_view`` is 1.
        worst_in_view: Lowest ``pnl / max_loss`` over the closed view, at least -1.
        tail_share: ``|E1 tails| / (|E1 tails| + |E1 inside| + 1e-12)``, the share of the
            expected profit and loss contributed beyond the outer knots, in [0, 1].
    """

    position: Position
    prob_profit: float
    expected_pnl: float
    pnl_std: float
    expected_return: float
    annualised_return: float
    reward_to_risk: float
    prob_view: float
    prob_profit_given_view: float
    return_if_right: float
    return_if_wrong: float
    worst_in_view: float
    tail_share: float


def score_structures(
    positions: Sequence[Position], dist: TailCompletedCdf, view: View
) -> list[StructureScore]:
    """Score many positions against one distribution and view, vectorised.

    Args:
        positions: Positions of the distribution's expiry (same ``years``).
        dist: The tail-completed distribution of the price at expiry.
        view: The outcome.

    Returns:
        One score per position, in input order; see ``StructureScore`` for units.

    Raises:
        EngineInputError: If a position's ``years`` differs from the distribution's.
    """
    if not positions:
        return []
    book = PositionBook(tuple(positions))
    moments = book.moments(dist, view)
    prob_profit, prob_profit_view = book.profit_probabilities(dist, view)
    p_view, p_out = moments.prob_view, moments.prob_out
    scores: list[StructureScore] = []
    for i, position in enumerate(book.positions):
        loss = position.max_loss
        e1 = float(moments.e1[i])
        std = math.sqrt(max(0.0, float(moments.e2[i]) - e1 * e1))
        if std <= _STD_FLOOR * loss:
            std = 0.0
        expected_return = e1 / loss
        e1_view = float(moments.e1_view[i])
        tails = abs(float(moments.e1_tails[i]))
        inside = abs(e1 - float(moments.e1_tails[i]))
        scores.append(
            StructureScore(
                position=position,
                prob_profit=float(min(1.0, prob_profit[i])),
                expected_pnl=e1,
                pnl_std=std,
                expected_return=expected_return,
                annualised_return=_annualise(expected_return, position.years),
                reward_to_risk=e1 / std if std > 0 else math.nan,
                prob_view=p_view,
                prob_profit_given_view=(
                    min(1.0, float(prob_profit_view[i]) / p_view)
                    if p_view > PROB_FLOOR
                    else math.nan
                ),
                return_if_right=e1_view / p_view / loss if p_view > PROB_FLOOR else math.nan,
                return_if_wrong=((e1 - e1_view) / p_out / loss if p_out > PROB_FLOOR else math.nan),
                worst_in_view=float(moments.worst_view[i]) / loss,
                tail_share=tails / (tails + inside + TAIL_SHARE_EPS),
            )
        )
    return scores


def score_structure(position: Position, dist: TailCompletedCdf, view: View) -> StructureScore:
    """Score one position against a distribution and a view.

    Args:
        position: The position.
        dist: The tail-completed distribution of the price at expiry, same ``years``.
        view: The outcome.

    Returns:
        The score; see ``StructureScore`` for units.

    Raises:
        EngineInputError: If the position's ``years`` differs from the distribution's.
    """
    return score_structures((position,), dist, view)[0]
