"""Synthetic option chains priced with Black-Scholes, for engine tests.

Strikes are in dollars, prices in dollars per share, volatility is a decimal and time is
in years. Rates are decimal APY, matching the engine.
"""

import math

import numpy as np

from oap.engine._types import FloatArray
from oap.engine.black_scholes import call_price, put_price


def lognormal_cdf(k: FloatArray, forward: float, vol: float, years: float) -> FloatArray:
    """Return the CDF of a lognormal price with the given forward.

    Args:
        k: Prices in dollars.
        forward: Mean of the price in dollars.
        vol: Volatility as a decimal.
        years: Time in years.

    Returns:
        Probability that the price is below each ``k``.
    """
    z = (np.log(k / forward) + 0.5 * vol * vol * years) / (vol * math.sqrt(years))
    return np.asarray(0.5 * np.vectorize(math.erfc)(-z / math.sqrt(2.0)), dtype=np.float64)


def synthetic_chain(
    spot: float, vol: float, years: float, rate: float, step_frac: float
) -> tuple[FloatArray, FloatArray, FloatArray, float]:
    """Build a Black-Scholes chain centred on the forward.

    Args:
        spot: Underlying price in dollars.
        vol: Volatility as a decimal.
        years: Time to expiry in years.
        rate: Risk-free APY as a decimal.
        step_frac: Strike step as a fraction of one standard deviation of the price.

    Returns:
        ``(strikes, put_mids, call_mids, forward)`` with strikes above ``0.2 * spot``.
    """
    forward = spot * (1.0 + rate) ** years
    h = step_frac * vol * math.sqrt(years) * forward
    m = math.ceil(3.0 / step_frac) + 1
    strikes = forward + h * np.arange(-m, m + 1)
    strikes = strikes[strikes > 0.2 * spot]
    puts = put_price(spot, strikes, years, rate, vol)
    calls = call_price(spot, strikes, years, rate, vol)
    return strikes, puts, calls, float(forward)
