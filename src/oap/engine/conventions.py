"""Day count and interest rate conventions for the engine.

Time is measured in years on an ACT/365 basis: calendar days between two dates divided by
365. Interest rates are decimal annual percentage yields (0.036 means 3.6% APY), so growth
over ``years`` is ``(1 + rate) ** years``. Prices are in dollars per share.
"""

import math
from datetime import date
from typing import Final

from oap.engine.errors import EngineInputError

DAYS_PER_YEAR: Final = 365


def dte_years(trade_date: date, expiration: date) -> float:
    """Return the time from trade date to expiration in years, ACT/365.

    Args:
        trade_date: Date of the quote.
        expiration: Option expiration date.

    Returns:
        Calendar days between the dates divided by 365, in years. Same-day expiry returns
        0.0; callers skip options with no time left.

    Raises:
        EngineInputError: If ``expiration`` is before ``trade_date``.
    """
    days = (expiration - trade_date).days
    if days < 0:
        raise EngineInputError("expiration must not be before trade_date")
    return days / DAYS_PER_YEAR


def growth_factor(rate: float, years: float) -> float:
    """Return the growth of one dollar at a decimal APY over a period in years.

    Args:
        rate: Annual percentage yield as a decimal (0.036 for 3.6%); must exceed -1.
        years: Period length in years; must be non-negative.

    Returns:
        ``(1 + rate) ** years``, a dimensionless multiplier.

    Raises:
        EngineInputError: If ``rate`` is not greater than -1 or ``years`` is negative.
    """
    if not (math.isfinite(rate) and rate > -1):
        raise EngineInputError("rate must be finite and greater than -1")
    if not (math.isfinite(years) and years >= 0):
        raise EngineInputError("years must be finite and non-negative")
    return float((1.0 + rate) ** years)


def discount_factor(rate: float, years: float) -> float:
    """Return the present value of one dollar due in ``years`` at a decimal APY.

    Args:
        rate: Annual percentage yield as a decimal; must exceed -1.
        years: Period length in years; must be non-negative.

    Returns:
        ``1 / (1 + rate) ** years``, a dimensionless multiplier.

    Raises:
        EngineInputError: If ``rate`` is not greater than -1 or ``years`` is negative.
    """
    return 1.0 / growth_factor(rate, years)


def continuous_rate(apy: float) -> float:
    """Convert a decimal APY to a continuously compounded rate.

    Args:
        apy: Annual percentage yield as a decimal (0.036 for 3.6%); must exceed -1.

    Returns:
        ``ln(1 + apy)`` as a decimal per year.

    Raises:
        EngineInputError: If ``apy`` is not finite or not greater than -1.
    """
    if not (math.isfinite(apy) and apy > -1):
        raise EngineInputError("apy must be finite and greater than -1")
    return math.log1p(apy)
