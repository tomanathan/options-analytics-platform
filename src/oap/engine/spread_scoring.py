"""Expected return on max loss for put credit spreads.

A put credit spread is short a higher-strike put and long a lower-strike put with the same
expiry. Per share, in dollars:

* the credit is received up front;
* the width is ``short_strike - long_strike``;
* the maximum loss, which is also the collateral held as cash, is ``width - credit``;
* the breakeven price at expiry is ``short_strike - credit``.

Scoring uses a ``RiskNeutralCdf`` (optionally recalibrated against realised outcomes) of
the underlying price at expiry:

* probability of profit is ``1 - F(breakeven)`` and probability of maximum loss is
  ``F(long_strike)``;
* the expected payoff, in dollars per share at expiry and undiscounted, is the credit
  minus the integral of ``F`` between the strikes (the expected payoff of the long put
  spread that offsets it);
* the interest on the collateral at a decimal APY ``cash_apy`` over ``years`` is
  ``collateral * ((1 + cash_apy) ** years - 1)``;
* the return on collateral is ``(expected_payoff + interest) / collateral``, and the
  annualised return is ``(1 + roc) ** (1 / years) - 1``.

For a cash-secured spread the collateral held equals the maximum loss, so the return on
collateral (the identifier ``expected_return_on_collateral``, ``expected_roc`` downstream) is
the expected return on max loss. Both names denote the same number; users see "return on max
loss".

Worked example. The chain has strikes 90, 95, 100 and 105 with put mids 0.50, 1.50, 3.50
and 7.00 dollars, 30 days (30 / 365 years) to expiry and a rate of 0. Its CDF has knots
92.5, 97.5 and 102.5 at probabilities 0.2, 0.4 and 0.7. Sell the 100 put and buy the 95
put for a credit of 2.00 dollars with cash at 3.6% APY:

* width 5.00 dollars, maximum loss and collateral 3.00 dollars, breakeven 98.00 dollars;
* probability of profit ``1 - F(98) = 1 - 0.43 = 0.57`` and probability of maximum loss
  ``F(95) = 0.30``;
* the expected payoff of the long 100/95 put spread is 2.0625 dollars (the integral of
  ``F`` from 95 to 100), so the expected payoff is ``2.00 - 2.0625 = -0.0625`` dollars;
* interest is ``3.00 * (1.036 ** (30 / 365) - 1) = 0.008733`` dollars;
* return on collateral, which is the return on max loss because the two are equal here, is
  ``(-0.0625 + 0.008733) / 3.00 = -0.017922``, which is ``-0.1975`` annualised;
* the Kelly fraction is 0 because the edge is negative.

Edge, fair credit and reward to risk. The long put spread that offsets the short one pays
``h(S) = min(max(K - S, 0), W)`` at expiry, where ``K`` is the short strike, ``L`` the long
strike and ``W = K - L``, so ``h`` lies in [0, W]. For any non-increasing ``phi`` with
``phi(inf) = 0``, ``E[phi(S)]`` equals the integral of ``-phi'(x) F(x)`` over ``x`` (Tonelli),
where ``F(x) = P(S < x)`` is ``prob_below``. The CDF is flat outside its knots, so the mass
below the lowest knot sits on the left of every price and pays ``W``, and the mass above the
highest knot pays 0; no tail term is needed. With ``phi = h`` this gives ``E[h]`` as the
integral of ``F`` from ``L`` to ``K`` (the fair credit); with ``phi = h**2`` it gives
``E[h**2]`` as the integral of ``2 (K - x) F(x)`` from ``L`` to ``K``. ``F`` is affine between
knots, so the integrand is quadratic on each segment and Simpson's rule is exact there.
``Var = max(0, E[h**2] - E[h]**2)`` and ``payoff_std = sqrt(Var)``, at most ``W / 2``
(Popoviciu). Interest on the collateral is deterministic, so the standard deviation of the
seller's profit and loss equals ``payoff_std``.

* the fair credit is the expected payout of the long spread, in dollars per share,
  undiscounted;
* the edge is ``expected_payoff = credit - fair_credit``, in dollars per share, and
  ``edge_pct = expected_payoff / credit`` is the edge as a share of the credit, at most 1;
* ``reward_to_risk = expected_payoff / payoff_std`` is per trade and not annualised. It is
  an excess-over-cash Sharpe ratio, because interest is the risk-free leg. It is nan when the
  standard deviation is 0.

Continuing the worked example (credit 2.00, hand CDF): ``E[h] = 2.0625`` so the fair credit is
2.0625 dollars; ``E[h**2] = 445 / 48 = 9.2708333`` square dollars; the variance is 5.0169271
and ``payoff_std = 2.2398498`` dollars; the edge is -0.0625 dollars, ``edge_pct = -0.03125``
and ``reward_to_risk = -0.0279037``.

Credits are in dollars per share and times are in years, so scores are comparable across
underlyings, widths and expiries.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

import numpy as np
import numpy.typing as npt

from oap.engine._validation import (
    as_float_1d,
    require_finite_scalar,
    require_non_negative,
    require_positive,
    require_same_length,
    require_strictly_increasing,
)
from oap.engine.calibration import CalibrationMap, apply_calibration
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import QualityFlag, RiskNeutralCdf

RankBy = Literal["return", "edge", "reward_to_risk"]

_YEARS_MATCH_TOL = 1e-9
_STD_FLOOR: Final = 1e-9  # payoff_std <= _STD_FLOOR * width is treated as 0


@dataclass(frozen=True)
class PutCreditSpread:
    """A put credit spread: short the higher-strike put, long the lower-strike put.

    Attributes:
        underlying: Ticker symbol of the underlying.
        expiration: Expiration date of both puts.
        short_strike: Strike of the sold put, in dollars.
        long_strike: Strike of the bought put, in dollars; below ``short_strike``.
        credit: Net credit received, in dollars per share; between 0 and the width.
        years: Time from trade date to expiration, in years.
    """

    underlying: str
    expiration: date
    short_strike: float
    long_strike: float
    credit: float
    years: float

    def __post_init__(self) -> None:
        """Validate the spread.

        Strikes and credit are in dollars per share and ``years`` is in years. Requires
        all values finite, ``0 < long_strike < short_strike``, ``0 < credit < width`` and
        ``years > 0``.

        Raises:
            EngineInputError: If any precondition is violated.
        """
        values = {
            "short_strike": self.short_strike,
            "long_strike": self.long_strike,
            "credit": self.credit,
            "years": self.years,
        }
        for name, value in values.items():
            require_finite_scalar(value, name)
        if not 0 < self.long_strike < self.short_strike:
            raise EngineInputError("strikes must satisfy 0 < long_strike < short_strike")
        if not 0 < self.credit < self.width:
            raise EngineInputError("credit must satisfy 0 < credit < width")
        if self.years <= 0:
            raise EngineInputError("years must be positive")

    @property
    def width(self) -> float:
        """Distance between the strikes, in dollars per share."""
        return self.short_strike - self.long_strike

    @property
    def max_loss(self) -> float:
        """Maximum loss at expiry, in dollars per share: width minus credit."""
        return self.width - self.credit

    @property
    def collateral(self) -> float:
        """Cash held against the spread, in dollars per share: equal to the maximum loss."""
        return self.max_loss

    @property
    def breakeven(self) -> float:
        """Underlying price at expiry where the spread breaks even, in dollars."""
        return self.short_strike - self.credit


@dataclass(frozen=True)
class SpreadScore:
    """Scored put credit spread.

    Attributes:
        spread: The spread that was scored.
        prob_profit: Probability the price at expiry is above breakeven, in [0, 1].
        prob_max_loss: Probability the price at expiry is below the long strike, in [0, 1].
        expected_payoff: Expected payoff at expiry in dollars per share, undiscounted.
        interest: Interest on the collateral over ``years`` in dollars per share.
        expected_return_on_collateral: Expected payoff plus interest over collateral, as
            a decimal for the holding period. Collateral equals the maximum loss for a
            cash-secured spread, so this is the expected return on max loss.
        annualised_return: Return on collateral (max loss) compounded to one year, as a
            decimal.
        kelly_fraction: Two-outcome Kelly fraction of capital, in [0, 1].
        fair_credit: Expected payout of the long put spread, in dollars per share,
            undiscounted, in [0, width]. ``expected_payoff`` is ``credit - fair_credit``.
        edge_pct: ``expected_payoff / credit``, a decimal share of the credit, at most 1.
        payoff_std: Standard deviation of the spread payoff (and of the seller's profit and
            loss) in dollars per share, in [0, width / 2].
        reward_to_risk: ``expected_payoff / payoff_std`` per trade, not annualised; nan when
            ``payoff_std`` is 0.
        calibrated: True if a calibration map was applied.
        extrapolated: True if the long strike is below the lowest CDF knot, so the
            probability of maximum loss relies on flat extrapolation.
        flags: Quality flags of the distribution used.
    """

    spread: PutCreditSpread
    prob_profit: float
    prob_max_loss: float
    expected_payoff: float
    interest: float
    expected_return_on_collateral: float
    annualised_return: float
    kelly_fraction: float
    fair_credit: float
    edge_pct: float
    payoff_std: float
    reward_to_risk: float
    calibrated: bool
    extrapolated: bool
    flags: frozenset[QualityFlag]


def _annualise(roc: float, years: float) -> float:
    """Compound a holding-period return to one year.

    Args:
        roc: Return over the holding period, as a decimal.
        years: Holding period in years.

    Returns:
        ``(1 + roc) ** (1 / years) - 1``; -1.0 if ``roc <= -1``; infinity on overflow.
    """
    if roc <= -1.0:
        return -1.0
    try:
        return math.expm1(math.log1p(roc) / years)
    except OverflowError:
        return math.inf


def put_spread_payoff_moments(
    cdf: RiskNeutralCdf, k_short: float, k_long: float
) -> tuple[float, float]:
    """Return the first two moments of the long put spread payoff at expiry.

    The payoff is ``h(S) = min(max(k_short - S, 0), k_short - k_long)`` per share. The first
    moment is ``cdf.expected_payoff_put_spread(k_short, k_long)`` verbatim. The second is the
    integral of ``2 (k_short - x) F(x)`` over the strikes, computed exactly: ``F`` is affine
    between knots, so Simpson's rule is exact on each segment of the grid made of both
    strikes and the knots strictly between them.

    Args:
        cdf: Risk-neutral CDF of the price at expiry, optionally calibrated.
        k_short: Higher strike in dollars.
        k_long: Lower strike in dollars; must be below ``k_short``.

    Returns:
        ``(E[h], E[h**2])`` in dollars per share and square dollars per share, undiscounted.

    Raises:
        EngineInputError: If ``k_long >= k_short``.
    """
    first = cdf.expected_payoff_put_spread(k_short, k_long)
    inside = cdf.strikes[(cdf.strikes > k_long) & (cdf.strikes < k_short)]
    grid = np.unique(np.concatenate([np.array([k_long, k_short]), inside]))
    mid = 0.5 * (grid[:-1] + grid[1:])

    def integrand(x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        return np.asarray(2.0 * (k_short - x) * cdf.prob_below_array(x), dtype=np.float64)

    q_grid = integrand(grid)
    q_mid = integrand(mid)
    simpson = (grid[1:] - grid[:-1]) / 6.0 * (q_grid[:-1] + 4.0 * q_mid + q_grid[1:])
    return first, float(np.sum(simpson))


def score_spread(
    spread: PutCreditSpread,
    cdf: RiskNeutralCdf,
    *,
    cash_apy: float,
    calibration: CalibrationMap | None = None,
) -> SpreadScore:
    """Score a put credit spread against a distribution of the price at expiry.

    Args:
        spread: The spread, with strikes and credit in dollars per share.
        cdf: Risk-neutral CDF for the same expiry; its ``years`` must match the spread's.
        cash_apy: Interest earned on the collateral, as a decimal APY (0.036 for 3.6%).
        calibration: Optional map applied to the CDF before scoring.

    Returns:
        The score; see ``SpreadScore`` for units (``fair_credit`` and ``payoff_std`` in
        dollars per share, ``edge_pct`` a decimal, ``reward_to_risk`` per trade). Collateral
        equals the maximum loss for a cash-secured spread, so
        ``expected_return_on_collateral`` is the expected return on max loss.

    Raises:
        EngineInputError: If ``years`` differ between spread and CDF by more than 1e-9, or
            ``cash_apy`` is not finite and greater than -1.
    """
    if abs(spread.years - cdf.years) > _YEARS_MATCH_TOL:
        raise EngineInputError("spread.years and cdf.years must match")
    if require_finite_scalar(cash_apy, "cash_apy") <= -1:
        raise EngineInputError("cash_apy must be greater than -1")
    dist = apply_calibration(cdf, calibration) if calibration is not None else cdf
    prob_profit = 1.0 - dist.prob_below(spread.breakeven)
    prob_max_loss = dist.prob_below(spread.long_strike)
    fair_credit, second_moment = put_spread_payoff_moments(
        dist, spread.short_strike, spread.long_strike
    )
    expected_payoff = spread.credit - fair_credit
    payoff_std = math.sqrt(max(0.0, second_moment - fair_credit * fair_credit))
    if payoff_std <= _STD_FLOOR * spread.width:
        payoff_std = 0.0
    reward_to_risk = expected_payoff / payoff_std if payoff_std > 0.0 else math.nan
    collateral = spread.collateral
    interest = collateral * ((1.0 + cash_apy) ** spread.years - 1.0)
    roc = (expected_payoff + interest) / collateral
    odds = spread.credit / spread.max_loss
    kelly = min(1.0, max(0.0, prob_profit - (1.0 - prob_profit) / odds))
    return SpreadScore(
        spread=spread,
        prob_profit=prob_profit,
        prob_max_loss=prob_max_loss,
        expected_payoff=expected_payoff,
        interest=interest,
        expected_return_on_collateral=roc,
        annualised_return=_annualise(roc, spread.years),
        kelly_fraction=kelly,
        fair_credit=fair_credit,
        edge_pct=expected_payoff / spread.credit,
        payoff_std=payoff_std,
        reward_to_risk=reward_to_risk,
        calibrated=calibration is not None,
        extrapolated=bool(spread.long_strike < dist.strikes[0]),
        flags=dist.flags,
    )


def enumerate_spreads(
    underlying: str,
    expiration: date,
    years: float,
    strikes: npt.ArrayLike,
    mids: npt.ArrayLike,
    *,
    min_width: float = 0.0,
    max_width: float = math.inf,
    min_credit: float = 0.0,
) -> list[PutCreditSpread]:
    """List the put credit spreads available from one expiry's put chain.

    For every pair of strikes ``K_i < K_j`` the spread sells ``K_j`` and buys ``K_i``
    for a credit of ``mids[j] - mids[i]``. Mid credits are optimistic: they assume
    fills at the midpoint. Callers may pass fillable prices (bid of the short put minus
    ask of the long put, per strike pair) in place of mids to score what can be traded.

    Args:
        underlying: Ticker symbol.
        expiration: Expiration date.
        years: Time to expiration in years; must be positive.
        strikes: Put strikes in dollars, at least 2, positive, strictly increasing.
        mids: Put prices in dollars per share, finite and non-negative, one per strike.
        min_width: Smallest strike width to keep, in dollars.
        max_width: Largest strike width to keep, in dollars.
        min_credit: Smallest credit to keep, in dollars per share.

    Returns:
        Spreads with ``min_width <= width <= max_width``, ``credit > 0``,
        ``credit >= min_credit`` and ``credit < width``, sorted by
        ``(short_strike, long_strike)`` ascending.

    Raises:
        EngineInputError: If the strikes, mids or years are invalid.
    """
    k = as_float_1d(strikes, "strikes", min_len=2)
    m = as_float_1d(mids, "mids", min_len=2)
    require_same_length(k, m, ("strikes", "mids"))
    require_positive(k, "strikes")
    require_strictly_increasing(k, "strikes")
    require_non_negative(m, "mids")
    if require_finite_scalar(years, "years") <= 0:
        raise EngineInputError("years must be positive")
    spreads: list[PutCreditSpread] = []
    for j in range(1, k.shape[0]):
        for i in range(j):
            width = float(k[j] - k[i])
            credit = float(m[j] - m[i])
            if not min_width <= width <= max_width:
                continue
            if credit <= 0 or credit < min_credit or credit >= width:
                continue
            spreads.append(
                PutCreditSpread(
                    underlying=underlying,
                    expiration=expiration,
                    short_strike=float(k[j]),
                    long_strike=float(k[i]),
                    credit=credit,
                    years=float(years),
                )
            )
    return spreads


def rank_spreads(
    scores: Iterable[SpreadScore], *, min_prob_profit: float = 0.0, by: RankBy = "return"
) -> list[SpreadScore]:
    """Filter and order scored spreads, best first.

    Args:
        scores: Scored spreads.
        min_prob_profit: Smallest probability of profit to keep, a decimal in [0, 1].
        by: Primary sort key. ``"return"`` is annualised return (descending), ``"edge"`` is
            ``edge_pct`` (descending) and ``"reward_to_risk"`` is reward to risk
            (descending, nan last).

    Returns:
        Scores with ``prob_profit >= min_prob_profit`` sorted by the primary key, then
        probability of profit (descending), then short strike in dollars (descending), then
        long strike in dollars (ascending).
    """
    kept = [s for s in scores if s.prob_profit >= min_prob_profit]
    if by == "edge":
        return sorted(
            kept,
            key=lambda s: (
                -s.edge_pct,
                -s.prob_profit,
                -s.spread.short_strike,
                s.spread.long_strike,
            ),
        )
    if by == "reward_to_risk":
        return sorted(
            kept,
            key=lambda s: (
                math.isnan(s.reward_to_risk),
                0.0 if math.isnan(s.reward_to_risk) else -s.reward_to_risk,
                -s.prob_profit,
                -s.spread.short_strike,
                s.spread.long_strike,
            ),
        )
    return sorted(
        kept,
        key=lambda s: (
            -s.annualised_return,
            -s.prob_profit,
            -s.spread.short_strike,
            s.spread.long_strike,
        ),
    )
