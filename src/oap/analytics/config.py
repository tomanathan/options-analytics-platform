"""Configuration for the calibration backtest and the live spread scoring.

Everything here is a plain value: prices are in dollars per share, interest rates are
decimal annual percentage yields (0.045 is 4.5% APY), times are in years or whole calendar
days, probabilities are decimals in [0, 1], and moneyness is a strike divided by the
underlying close, a dimensionless ratio.

Rate source. ``risk_free_apy`` is one documented constant. Phase 4 will load the daily
3-month T-bill yield (FRED DTB3) into bronze and use the rate of each trade date. The
bias of a constant is small: the rate enters the CDF through the growth factor
``g = (1 + rate) ** years``, which scales the forward and the slopes by ``g``. Using 4.5%
APY instead of 0% at the longest horizon in the data (about 0.18 years, 67 days) moves the
forward by at most 0.8% relative, and by about 0.35% at the median horizon. The
calibration map, fitted on outcomes computed with the same constant, absorbs the average
of that bias; the report lists it as a caveat.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from oap.engine.calibration import DEFAULT_BINS, MIN_FIT_SAMPLES

MONEYNESS_GRID: Final[tuple[float, ...]] = tuple(round(0.800 + 0.025 * i, 3) for i in range(13))
"""Target strikes as a fraction of the underlying close: 0.800, 0.825, ..., 1.100."""

PRODUCTION_MAP_ID: Final = "production"
"""Identifier of the calibration map fitted on every settled prediction."""

RankBy = Literal[
    "return_mid", "return_natural", "reward_to_risk", "kelly_growth", "pop_shrunk_return"
]
"""A ranking of scored spreads; ``oap.analytics.ranking.rank_score`` defines each one."""

RANK_BYS: Final[tuple[RankBy, ...]] = (
    "return_mid",
    "return_natural",
    "reward_to_risk",
    "kelly_growth",
    "pop_shrunk_return",
)
"""Every ranking, in the order of the rule lab grid."""

DTE_BUCKET_EDGES: Final[tuple[int, ...]] = (20, 35, 50)
"""Upper edges, in calendar days, of the first three days-to-expiry buckets."""

DTE_BUCKETS: Final[tuple[str, ...]] = ("<=20d", "21-35d", "36-50d", ">50d")
"""Names of the days-to-expiry buckets, shortest first."""


def fold_map_id(year: int) -> str:
    """Return the identifier of the walk-forward map applied to one calendar year.

    Args:
        year: Calendar year of the fold, such as 2021.

    Returns:
        The identifier, such as ``"fold_2021"``.
    """
    return f"fold_{year}"


def dte_bucket(dte_days: int) -> str:
    """Return the days-to-expiry bucket of a snapshot.

    Args:
        dte_days: Calendar days from the trade date to expiration.

    Returns:
        ``"<=20d"``, ``"21-35d"``, ``"36-50d"`` or ``">50d"``.
    """
    for edge, name in zip(DTE_BUCKET_EDGES, DTE_BUCKETS, strict=False):
        if dte_days <= edge:
            return name
    return DTE_BUCKETS[-1]


@dataclass(frozen=True)
class AnalyticsConfig:
    """Parameters of the calibration backtest and spread scoring.

    Attributes:
        risk_free_apy: Constant risk-free rate used to build every CDF, as a decimal
            APY. See the module docstring for the size of the bias.
        cash_apy: Interest earned on spread collateral, as a decimal APY.
        moneyness_grid: Target strikes as fractions of the underlying close, strictly
            increasing and positive.
        min_dte_days: Shortest time to expiration kept, in calendar days.
        split_abs_log_return: A daily absolute log return above this (a dimensionless
            decimal) is treated as an unadjusted stock split.
        ticker_valid_from: ``(underlying, first date)`` pairs; quotes before the date
            belong to a different company that used the symbol.
        first_test_year: First calendar year whose predictions count as out of sample;
            earlier years are burn-in for the walk-forward fit.
        min_fit_samples: Fewest outcomes needed to fit a calibration map.
        bins: Number of equal-width probability bins for reliability tables and ECE.
        bootstrap_resamples: Number of cluster-bootstrap resamples.
        bootstrap_seed: Seed of the bootstrap random generator.
        max_width_fraction: Widest spread kept, as a fraction of the underlying close.
        min_credit: Smallest mid credit kept, in dollars per share.
        min_prob_profit: Smallest calibrated probability of profit for an eligible
            spread, a decimal in [0, 1].
        min_edge_credit: Smallest mid credit, in dollars per share, for a spread to enter
            the edge, reward-to-risk and entry rankings.
        min_natural_fraction: Smallest natural credit as a share of the mid credit, a decimal
            in [0, 1], for a spread to enter those rankings.
        entry_min_pop: Smallest calibrated probability of profit, a decimal in [0, 1], for
            a spread to enter the entry ranking.
        entry_dte_band: ``(lo, hi)`` calendar days to expiry of the entry ranking, keeping
            ``lo <= dte_days < hi``.
        entry_moneyness_band: ``(lo, hi)`` short strike over close of the entry ranking, keeping
            ``lo <= short_moneyness < hi``.
        entry_rank: The ranking that orders the entry candidates (``score_entry``); see
            ``oap.analytics.ranking.rank_score``.
    """

    risk_free_apy: float = 0.045
    cash_apy: float = 0.036
    moneyness_grid: tuple[float, ...] = MONEYNESS_GRID
    min_dte_days: int = 7
    split_abs_log_return: float = 0.4
    ticker_valid_from: tuple[tuple[str, date], ...] = (("META", date(2022, 6, 9)),)
    first_test_year: int = 2021
    min_fit_samples: int = MIN_FIT_SAMPLES
    bins: int = DEFAULT_BINS
    bootstrap_resamples: int = 200
    bootstrap_seed: int = 20200106
    max_width_fraction: float = 0.10
    min_credit: float = 0.10
    min_prob_profit: float = 0.5
    min_edge_credit: float = 0.25
    min_natural_fraction: float = 0.5
    entry_min_pop: float = 0.65
    entry_dte_band: tuple[int, int] = (45, 70)
    entry_moneyness_band: tuple[float, float] = (0.95, 1.00)
    entry_rank: RankBy = "pop_shrunk_return"

    def __post_init__(self) -> None:
        """Validate ranges.

        Rates are decimal APYs and must exceed -1; moneyness values must be positive and
        strictly increasing; ``min_dte_days`` is in calendar days and at least 1;
        ``split_abs_log_return`` and ``max_width_fraction`` are positive decimals;
        ``min_credit`` and ``min_edge_credit`` are non-negative dollars per share;
        ``min_prob_profit``, ``min_natural_fraction`` and ``entry_min_pop`` lie in [0, 1];
        counts must be positive; ``entry_dte_band`` is ``0 <= lo < hi`` calendar days,
        ``entry_moneyness_band`` is ``0 < lo < hi``, and ``entry_rank`` is one of
        ``RANK_BYS``.

        Raises:
            ValueError: If any value is out of range.
        """
        if not self.risk_free_apy > -1:
            raise ValueError("risk_free_apy must be greater than -1")
        if not self.cash_apy > -1:
            raise ValueError("cash_apy must be greater than -1")
        grid = self.moneyness_grid
        if (
            len(grid) == 0
            or grid[0] <= 0
            or any(b <= a for a, b in zip(grid, grid[1:], strict=False))
        ):
            raise ValueError("moneyness_grid must be positive and strictly increasing")
        if self.min_dte_days < 1:
            raise ValueError("min_dte_days must be at least 1")
        if not self.split_abs_log_return > 0:
            raise ValueError("split_abs_log_return must be positive")
        if self.min_fit_samples < 1:
            raise ValueError("min_fit_samples must be at least 1")
        if self.bins < 1:
            raise ValueError("bins must be at least 1")
        if self.bootstrap_resamples < 1:
            raise ValueError("bootstrap_resamples must be at least 1")
        if not 0 < self.max_width_fraction <= 1:
            raise ValueError("max_width_fraction must be in (0, 1]")
        if not self.min_credit >= 0:
            raise ValueError("min_credit must be non-negative")
        if not 0.0 <= self.min_prob_profit <= 1.0:
            raise ValueError("min_prob_profit must be in [0, 1]")
        if not self.min_edge_credit >= 0:
            raise ValueError("min_edge_credit must be non-negative")
        if not 0.0 <= self.min_natural_fraction <= 1.0:
            raise ValueError("min_natural_fraction must be in [0, 1]")
        if not 0.0 <= self.entry_min_pop <= 1.0:
            raise ValueError("entry_min_pop must be in [0, 1]")
        dte_lo, dte_hi = self.entry_dte_band
        if not 0 <= dte_lo < dte_hi:
            raise ValueError("entry_dte_band must have 0 <= lo < hi")
        money_lo, money_hi = self.entry_moneyness_band
        if not 0 < money_lo < money_hi:
            raise ValueError("entry_moneyness_band must have 0 < lo < hi")
        if self.entry_rank not in RANK_BYS:
            raise ValueError(f"unknown entry_rank {self.entry_rank!r}")


DEFAULT_CONFIG: Final = AnalyticsConfig()
