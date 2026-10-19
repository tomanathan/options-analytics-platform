"""Filter and describe the scored put credit spreads of ``gold.spread_scores``.

Pure functions over frames and CDFs: no I/O and no state.

Units: strikes, credits, losses and widths are in dollars per share ($/sh); probabilities and
returns on max loss are decimals; time is in years (ACT/365); densities are probability per
dollar (1/$).
"""

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

import numpy as np
import pandas as pd

from oap.api.landscape import ExpiryCurves, finite_or_none
from oap.api.models import (
    PayoffPoint,
    RawCalibrated,
    SpreadDetail,
    SpreadRegions,
    SpreadRow,
)
from oap.engine.implied_distribution import RiskNeutralCdf

MAX_SPREAD_ROWS: Final = 5000
"""Most rows one response carries."""

PAYOFF_POINTS: Final = 161
"""Points of the payoff grid, before the strikes and the breakeven are added."""

WIDTHS_BELOW: Final = 2.0
"""The payoff grid reaches this many widths below the long strike and above the short."""

CLOSE_PAD: Final = 0.04
"""The payoff grid reaches this fraction of the close past the breakeven and the close."""


@dataclass(frozen=True)
class SpreadFilters:
    """The filters of ``GET /api/spreads``.

    Attributes:
        underlyings: Underlyings to keep; all when empty.
        expiration: Expiration to keep; all when None.
        min_width: Narrowest spread in dollars per share; no bound when None.
        max_width: Widest spread in dollars per share; no bound when None.
        min_pop: Smallest calibrated probability of profit, a decimal.
        min_credit: Smallest mid credit in dollars per share.
        eligible_only: Keep only eligible spreads.
        limit: Most rows returned.
    """

    underlyings: tuple[str, ...] = ()
    expiration: date | None = None
    min_width: float | None = None
    max_width: float | None = None
    min_pop: float = 0.0
    min_credit: float = 0.0
    eligible_only: bool = True
    limit: int = MAX_SPREAD_ROWS


def prepare_spreads(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalise the dtypes of the spread table once, after it is read.

    Args:
        frame: ``gold.spread_scores`` with ``datetime64`` dates.

    Returns:
        A copy whose ``rank`` is a nullable integer and whose ``flags`` are strings, sorted
        by rank ascending with nulls last and then by ``annualised_roc`` descending.
    """
    out = frame.copy()
    out["rank"] = pd.to_numeric(out["rank"]).astype("Int64")
    out["flags"] = out["flags"].fillna("").astype(str)
    return out.sort_values(
        ["rank", "annualised_roc"], ascending=[True, False], na_position="last", kind="stable"
    ).reset_index(drop=True)


def filter_spreads(frame: pd.DataFrame, filters: SpreadFilters) -> pd.DataFrame:
    """Apply the filters, keeping the order of ``prepare_spreads``.

    Args:
        frame: Output of ``prepare_spreads``.
        filters: The filters; ``limit`` is not applied here.

    Returns:
        The rows that match every filter, in the frame's order.
    """
    keep = pd.Series(True, index=frame.index)
    if filters.eligible_only:
        keep &= frame["eligible"].astype(bool)
    if filters.underlyings:
        keep &= frame["underlying"].isin(filters.underlyings)
    if filters.expiration is not None:
        keep &= frame["expiration"] == pd.Timestamp(filters.expiration)
    if filters.min_width is not None:
        keep &= frame["width"] >= filters.min_width
    if filters.max_width is not None:
        keep &= frame["width"] <= filters.max_width
    keep &= frame["prob_profit"] >= filters.min_pop
    keep &= frame["credit"] >= filters.min_credit
    return frame.loc[keep]


def _flags(text: object) -> list[str]:
    """Split a comma-joined flag string.

    Args:
        text: The ``flags`` column value.

    Returns:
        The flags in order; empty for an empty or null string.
    """
    return [f for f in str(text).split(",") if f] if isinstance(text, str) else []


def _rank(value: Any) -> int | None:
    """Return a rank as an int, or None for a null.

    Args:
        value: The ``rank`` column value.

    Returns:
        The rank, or None when it is null.
    """
    return None if value is None or pd.isna(value) else int(value)


def _row(record: Mapping[Hashable, Any]) -> SpreadRow:
    """Build one response row from a record of ``prepare_spreads``.

    Args:
        record: One row of the spread table as a mapping.

    Returns:
        The response row; non-finite ``annualised_roc`` becomes None.
    """
    return SpreadRow(
        spread_key=str(record["spread_key"]),
        underlying=str(record["underlying"]),
        expiration=pd.Timestamp(str(record["expiration"])).date(),
        dte_days=int(record["dte_days"]),
        short_strike=float(record["short_strike"]),
        long_strike=float(record["long_strike"]),
        width=float(record["width"]),
        credit=float(record["credit"]),
        credit_natural=float(record["credit_natural"]),
        max_loss=float(record["max_loss"]),
        breakeven=float(record["breakeven"]),
        short_moneyness=float(record["short_moneyness"]),
        prob_profit=float(record["prob_profit"]),
        prob_profit_raw=float(record["prob_profit_raw"]),
        prob_max_loss=float(record["prob_max_loss"]),
        expected_roc=float(record["expected_roc"]),
        expected_roc_raw=float(record["expected_roc_raw"]),
        annualised_roc=finite_or_none(record["annualised_roc"]),
        kelly_fraction=float(record["kelly_fraction"]),
        eligible=bool(record["eligible"]),
        rank=_rank(record["rank"]),
        extrapolated=bool(record["extrapolated"]),
        flags=_flags(record["flags"]),
    )


def spread_rows(frame: pd.DataFrame, limit: int = MAX_SPREAD_ROWS) -> list[SpreadRow]:
    """Convert the first rows of a spread table to response rows.

    Args:
        frame: Rows from ``filter_spreads``.
        limit: Most rows converted.

    Returns:
        One response row per spread, in the frame's order.
    """
    return [_row(record) for record in frame.head(limit).to_dict("records")]


def payoff_curve(
    short: float, long: float, credit: float, breakeven: float, close: float
) -> list[PayoffPoint]:
    """Return the payoff at expiry of a put credit spread over a grid of prices.

    The grid runs from ``min(long - 2 * width, breakeven - 0.04 * close)`` (floored at zero)
    to ``max(short + 2 * width, 1.04 * close)`` in 161 steps, with the long strike, the short
    strike and the breakeven added. The payoff is ``credit - max(short - S, 0) +
    max(long - S, 0)``, before interest.

    Args:
        short: Strike of the sold put in dollars.
        long: Strike of the bought put in dollars, below ``short``.
        credit: Net credit in dollars per share.
        breakeven: Breakeven price in dollars.
        close: Underlying close in dollars.

    Returns:
        Points sorted by price, with unique prices.
    """
    width = short - long
    lo = max(0.0, min(long - WIDTHS_BELOW * width, breakeven - CLOSE_PAD * close))
    hi = max(short + WIDTHS_BELOW * width, (1.0 + CLOSE_PAD) * close)
    prices = np.unique(
        np.concatenate([np.linspace(lo, hi, PAYOFF_POINTS), [long, short, breakeven]])
    )
    payoff = credit - np.maximum(short - prices, 0.0) + np.maximum(long - prices, 0.0)
    return [
        PayoffPoint(price=float(p), payoff=float(v)) for p, v in zip(prices, payoff, strict=True)
    ]


def _regions(cdf: RiskNeutralCdf, long: float, breakeven: float) -> tuple[float, float, float]:
    """Return the probabilities of the three payoff regions on one CDF.

    Args:
        cdf: A risk-neutral CDF.
        long: Long strike in dollars.
        breakeven: Breakeven price in dollars.

    Returns:
        ``(P(S <= long), P(long < S < breakeven), P(S >= breakeven))`` as decimals.
    """
    below_long = cdf.prob_below(long)
    below_breakeven = cdf.prob_below(breakeven)
    return below_long, below_breakeven - below_long, 1.0 - below_breakeven


def spread_detail(row: pd.Series, curves: ExpiryCurves) -> SpreadDetail:
    """Describe one spread: every gold column, its payoff curve and the densities behind it.

    The densities and the region probabilities come from the same CDFs the gold row was
    scored on (``chain_cdf`` and the row's calibration map), so ``1 - F(breakeven)`` on the
    calibrated CDF equals the row's ``prob_profit``.

    Args:
        row: One row of ``gold.spread_scores`` (as prepared by ``prepare_spreads``).
        curves: The CDFs of the row's expiration, built with the row's ``map_id``.

    Returns:
        The detail.
    """
    base = _row(row.to_dict())
    short, long = base.short_strike, base.long_strike
    raw = _regions(curves.cdf, long, base.breakeven)
    cal = _regions(curves.cal, long, base.breakeven)
    return SpreadDetail(
        **base.model_dump(),
        trade_date=pd.Timestamp(str(row["trade_date"])).date(),
        years=float(row["years"]),
        underlying_close=float(row["underlying_close"]),
        expected_payoff=float(row["expected_payoff"]),
        interest=float(row["interest"]),
        annualised_roc_raw=finite_or_none(row["annualised_roc_raw"]),
        calibrated=bool(row["calibrated"]),
        map_id=str(row["map_id"]),
        cash_apy=float(row["cash_apy"]),
        risk_free_apy=float(row["risk_free_apy"]),
        forward=finite_or_none(curves.forward),
        payoff=payoff_curve(short, long, base.credit, base.breakeven, curves.close),
        density_mid=curves.curve.density_mid,
        density_raw=curves.curve.density,
        density_calibrated=curves.curve.density_calibrated,
        regions=SpreadRegions(
            prob_max_loss=RawCalibrated(raw=raw[0], calibrated=cal[0]),
            prob_partial_loss=RawCalibrated(raw=raw[1], calibrated=cal[1]),
            prob_profit=RawCalibrated(raw=raw[2], calibrated=cal[2]),
        ),
        knot_range=(float(curves.cdf.strikes[0]), float(curves.cdf.strikes[-1])),
    )
