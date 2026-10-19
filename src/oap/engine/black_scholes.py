"""Black-Scholes-Merton pricing, greeks and implied volatility for European options.

Units: spot, strike and option prices are in dollars per share; volatility is a decimal
(0.20, not 20%); time is in years (ACT/365); the risk-free rate and dividend yield are
decimal annual percentage yields (APY), converted internally to continuously compounded
rates with ``log1p``. A textbook continuous rate of 0.05 is therefore passed as
``math.expm1(0.05)``.

With ``t`` years, ``r_c = ln(1 + rate)``, ``q_c = ln(1 + dividend_yield)`` and
``sd = vol * sqrt(t)``::

    d1 = (ln(spot / strike) + (r_c - q_c + vol**2 / 2) * t) / sd
    d2 = d1 - sd
    call = spot * exp(-q_c t) * N(d1) - strike * exp(-r_c t) * N(d2)
    put  = strike * exp(-r_c t) * N(-d2) - spot * exp(-q_c t) * N(-d1)

Every price, greek and bound function broadcasts its inputs and returns a float64 array
(0-d for scalar inputs); use ``float(...)`` to get a Python scalar.
"""

import math
from typing import Final

import numpy as np
import numpy.typing as npt

from oap.engine._types import BoolArray, FloatArray, Right
from oap.engine._validation import (
    as_float_1d,
    require_same_length,
    require_strictly_increasing,
)
from oap.engine.errors import EngineInputError

VOL_MIN: Final = 1e-6
VOL_MAX: Final = 10.0
VOL_TOL: Final = 1e-12
MAX_ITER: Final = 200

_SQRT2: Final = math.sqrt(2.0)
_SQRT_2PI: Final = math.sqrt(2.0 * math.pi)
_ERFC = np.vectorize(math.erfc, otypes=[np.float64])


def _norm_cdf(x: FloatArray) -> FloatArray:
    """Return the standard normal CDF, accurate to double precision in the tails.

    Args:
        x: Standard normal quantiles (dimensionless).

    Returns:
        ``0.5 * erfc(-x / sqrt(2))`` as probabilities in [0, 1].
    """
    return np.asarray(0.5 * _ERFC(-x / _SQRT2), dtype=np.float64)


def _norm_pdf(x: FloatArray) -> FloatArray:
    """Return the standard normal density.

    Args:
        x: Standard normal quantiles (dimensionless).

    Returns:
        ``exp(-x**2 / 2) / sqrt(2 pi)`` (dimensionless density).
    """
    return np.asarray(np.exp(-0.5 * x * x) / _SQRT_2PI, dtype=np.float64)


def _array(x: npt.ArrayLike, name: str) -> FloatArray:
    """Convert to a float64 array of any shape, requiring numeric input.

    Args:
        x: Scalar or array in the caller's units.
        name: Argument name used in error messages.

    Returns:
        A float64 array (0-d for scalars).

    Raises:
        EngineInputError: If the input is not numeric.
    """
    try:
        return np.asarray(x, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise EngineInputError(f"{name} must be numeric") from exc


def _require(arr: FloatArray, name: str, ok: BoolArray, rule: str) -> None:
    """Raise if any element violates ``rule`` or is not finite.

    Args:
        arr: Values being checked.
        name: Argument name used in error messages.
        ok: Element-wise result of the rule.
        rule: Human-readable rule, such as "positive".

    Raises:
        EngineInputError: If any value is non-finite or violates the rule.
    """
    if not np.all(np.isfinite(arr)):
        raise EngineInputError(f"{name} must be finite")
    if not np.all(ok):
        raise EngineInputError(f"{name} must be {rule}")


def _check_market(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    rate: npt.ArrayLike,
    dividend_yield: npt.ArrayLike,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
    """Validate and convert the market inputs shared by every function.

    Args:
        spot: Underlying price in dollars; must be positive.
        strike: Strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        dividend_yield: Dividend yield APY as a decimal; must exceed -1.

    Returns:
        The five inputs as float64 arrays, in the same order.

    Raises:
        EngineInputError: If any value is non-finite or out of range.
    """
    s = _array(spot, "spot")
    k = _array(strike, "strike")
    t = _array(years, "years")
    r = _array(rate, "rate")
    q = _array(dividend_yield, "dividend_yield")
    _require(s, "spot", s > 0, "positive")
    _require(k, "strike", k > 0, "positive")
    _require(t, "years", t > 0, "positive")
    _require(r, "rate", r > -1, "greater than -1")
    _require(q, "dividend_yield", q > -1, "greater than -1")
    return s, k, t, r, q


def _check_vol(vol: npt.ArrayLike) -> FloatArray:
    """Validate a volatility input.

    Args:
        vol: Volatility as a decimal (0.20 for 20%); must be positive.

    Returns:
        The volatility as a float64 array.

    Raises:
        EngineInputError: If any value is non-finite or not positive.
    """
    v = _array(vol, "vol")
    _require(v, "vol", v > 0, "positive")
    return v


def _check_right(right: str) -> None:
    """Validate an option right code.

    Args:
        right: "C" for call or "P" for put.

    Raises:
        EngineInputError: If the code is neither "C" nor "P".
    """
    if right not in ("C", "P"):
        raise EngineInputError("right must be 'C' or 'P'")


def _d1_d2(
    spot: FloatArray,
    strike: FloatArray,
    years: FloatArray,
    r_c: FloatArray,
    q_c: FloatArray,
    vol: FloatArray,
) -> tuple[FloatArray, FloatArray]:
    """Return d1 and d2 without validating inputs.

    Args:
        spot: Underlying price in dollars.
        strike: Strike in dollars.
        years: Time to expiry in years.
        r_c: Continuously compounded risk-free rate, per year.
        q_c: Continuously compounded dividend yield, per year.
        vol: Volatility as a decimal.

    Returns:
        ``(d1, d2)``, both dimensionless.
    """
    sd = vol * np.sqrt(years)
    d1 = (np.log(spot / strike) + (r_c - q_c + 0.5 * vol * vol) * years) / sd
    return d1, d1 - sd


def _price(
    spot: FloatArray,
    strike: FloatArray,
    years: FloatArray,
    r_c: FloatArray,
    q_c: FloatArray,
    vol: FloatArray,
    is_call: bool,
) -> FloatArray:
    """Return the option price without validating inputs.

    Args:
        spot: Underlying price in dollars.
        strike: Strike in dollars.
        years: Time to expiry in years.
        r_c: Continuously compounded risk-free rate, per year.
        q_c: Continuously compounded dividend yield, per year.
        vol: Volatility as a decimal.
        is_call: True for a call, False for a put.

    Returns:
        Option price in dollars per share.
    """
    d1, d2 = _d1_d2(spot, strike, years, r_c, q_c, vol)
    df_r = np.exp(-r_c * years)
    df_q = np.exp(-q_c * years)
    if is_call:
        price = spot * df_q * _norm_cdf(d1) - strike * df_r * _norm_cdf(d2)
    else:
        price = strike * df_r * _norm_cdf(-d2) - spot * df_q * _norm_cdf(-d1)
    return np.asarray(price, dtype=np.float64)


def option_price(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    rate: npt.ArrayLike,
    vol: npt.ArrayLike,
    right: Right,
    *,
    dividend_yield: npt.ArrayLike = 0.0,
) -> FloatArray:
    """Return the Black-Scholes price of a European option.

    Args:
        spot: Underlying price in dollars; must be positive.
        strike: Strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        vol: Volatility as a decimal (0.20 for 20%); must be positive.
        right: "C" for a call, "P" for a put.
        dividend_yield: Continuous-dividend APY as a decimal; must exceed -1.

    Returns:
        Option price in dollars per share, broadcast over the inputs (0-d for scalars).

    Raises:
        EngineInputError: If any input is non-finite or out of range, or ``right`` is
            invalid.
    """
    _check_right(right)
    s, k, t, r, q = _check_market(spot, strike, years, rate, dividend_yield)
    v = _check_vol(vol)
    return _price(s, k, t, np.log1p(r), np.log1p(q), v, right == "C")


def call_price(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    rate: npt.ArrayLike,
    vol: npt.ArrayLike,
    *,
    dividend_yield: npt.ArrayLike = 0.0,
) -> FloatArray:
    """Return the Black-Scholes price of a European call.

    Args:
        spot: Underlying price in dollars; must be positive.
        strike: Strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        vol: Volatility as a decimal (0.20 for 20%); must be positive.
        dividend_yield: Continuous-dividend APY as a decimal; must exceed -1.

    Returns:
        Call price in dollars per share, broadcast over the inputs.

    Raises:
        EngineInputError: If any input is non-finite or out of range.
    """
    return option_price(spot, strike, years, rate, vol, "C", dividend_yield=dividend_yield)


def put_price(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    rate: npt.ArrayLike,
    vol: npt.ArrayLike,
    *,
    dividend_yield: npt.ArrayLike = 0.0,
) -> FloatArray:
    """Return the Black-Scholes price of a European put.

    Args:
        spot: Underlying price in dollars; must be positive.
        strike: Strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        vol: Volatility as a decimal (0.20 for 20%); must be positive.
        dividend_yield: Continuous-dividend APY as a decimal; must exceed -1.

    Returns:
        Put price in dollars per share, broadcast over the inputs.

    Raises:
        EngineInputError: If any input is non-finite or out of range.
    """
    return option_price(spot, strike, years, rate, vol, "P", dividend_yield=dividend_yield)


def delta(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    rate: npt.ArrayLike,
    vol: npt.ArrayLike,
    right: Right,
    *,
    dividend_yield: npt.ArrayLike = 0.0,
) -> FloatArray:
    """Return the option delta, the derivative of price with respect to spot.

    Args:
        spot: Underlying price in dollars; must be positive.
        strike: Strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        vol: Volatility as a decimal (0.20 for 20%); must be positive.
        right: "C" for a call, "P" for a put.
        dividend_yield: Continuous-dividend APY as a decimal; must exceed -1.

    Returns:
        Delta in dollars of option price per dollar of spot (dimensionless): in
        ``[0, exp(-q_c t)]`` for calls and ``[-exp(-q_c t), 0]`` for puts.

    Raises:
        EngineInputError: If any input is non-finite or out of range, or ``right`` is
            invalid.
    """
    _check_right(right)
    s, k, t, r, q = _check_market(spot, strike, years, rate, dividend_yield)
    v = _check_vol(vol)
    q_c = np.log1p(q)
    d1, _ = _d1_d2(s, k, t, np.log1p(r), q_c, v)
    df_q = np.exp(-q_c * t)
    cdf = _norm_cdf(d1)
    result = df_q * cdf if right == "C" else df_q * (cdf - 1.0)
    return np.asarray(result, dtype=np.float64)


def vega(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    rate: npt.ArrayLike,
    vol: npt.ArrayLike,
    *,
    dividend_yield: npt.ArrayLike = 0.0,
) -> FloatArray:
    """Return vega, the derivative of option price with respect to volatility.

    Args:
        spot: Underlying price in dollars; must be positive.
        strike: Strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        vol: Volatility as a decimal (0.20 for 20%); must be positive.
        dividend_yield: Continuous-dividend APY as a decimal; must exceed -1.

    Returns:
        Vega in dollars per share per 1.00 of volatility (so per 0.01 of vol, divide by
        100). Identical for calls and puts.

    Raises:
        EngineInputError: If any input is non-finite or out of range.
    """
    s, k, t, r, q = _check_market(spot, strike, years, rate, dividend_yield)
    v = _check_vol(vol)
    q_c = np.log1p(q)
    d1, _ = _d1_d2(s, k, t, np.log1p(r), q_c, v)
    return np.asarray(s * np.exp(-q_c * t) * _norm_pdf(d1) * np.sqrt(t), dtype=np.float64)


def price_bounds(
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    rate: npt.ArrayLike,
    right: Right,
    *,
    dividend_yield: npt.ArrayLike = 0.0,
) -> tuple[FloatArray, FloatArray]:
    """Return the no-arbitrage bounds on a European option price.

    For a call the bounds are ``[max(0, spot*df_q - strike*df_r), spot*df_q]``; for a put
    ``[max(0, strike*df_r - spot*df_q), strike*df_r]``, where ``df_r`` and ``df_q`` are
    the discount factors over ``years`` at the rate and dividend yield (APY).

    Args:
        spot: Underlying price in dollars; must be positive.
        strike: Strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        right: "C" for a call, "P" for a put.
        dividend_yield: Continuous-dividend APY as a decimal; must exceed -1.

    Returns:
        ``(lower, upper)`` in dollars per share, broadcast over the inputs.

    Raises:
        EngineInputError: If any input is non-finite or out of range, or ``right`` is
            invalid.
    """
    _check_right(right)
    s, k, t, r, q = _check_market(spot, strike, years, rate, dividend_yield)
    return _bounds(s, k, t, np.log1p(r), np.log1p(q), right == "C")


def _bounds(
    spot: FloatArray,
    strike: FloatArray,
    years: FloatArray,
    r_c: FloatArray,
    q_c: FloatArray,
    is_call: bool,
) -> tuple[FloatArray, FloatArray]:
    """Return the no-arbitrage price bounds without validating inputs.

    Args:
        spot: Underlying price in dollars.
        strike: Strike in dollars.
        years: Time to expiry in years.
        r_c: Continuously compounded risk-free rate, per year.
        q_c: Continuously compounded dividend yield, per year.
        is_call: True for a call, False for a put.

    Returns:
        ``(lower, upper)`` in dollars per share.
    """
    pv_spot = spot * np.exp(-q_c * years)
    pv_strike = strike * np.exp(-r_c * years)
    if is_call:
        lower = np.maximum(0.0, pv_spot - pv_strike)
        upper = pv_spot
    else:
        lower = np.maximum(0.0, pv_strike - pv_spot)
        upper = pv_strike
    return np.asarray(lower, dtype=np.float64), np.asarray(upper, dtype=np.float64)


def implied_vol(
    price: npt.ArrayLike,
    spot: npt.ArrayLike,
    strike: npt.ArrayLike,
    years: npt.ArrayLike,
    rate: npt.ArrayLike,
    right: Right,
    *,
    dividend_yield: npt.ArrayLike = 0.0,
) -> FloatArray:
    """Return the Black-Scholes implied volatility by vectorised bisection.

    Bisection on ``[1e-6, 10]`` always converges inside the bracket (price is increasing
    in volatility), to a width of 1e-12 or at most 200 iterations.

    Args:
        price: Option price in dollars per share; may be nan.
        spot: Underlying price in dollars; must be positive.
        strike: Strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.
        right: "C" for a call, "P" for a put.
        dividend_yield: Continuous-dividend APY as a decimal; must exceed -1.

    Returns:
        Implied volatility as a decimal (0.20 for 20%), broadcast over the inputs. An
        element is nan when its price is nan, outside the no-arbitrage bounds, or outside
        the volatility range [1e-6, 10], so one bad quote does not abort a chain.

    Raises:
        EngineInputError: If any input other than ``price`` is non-finite or out of
            range, or ``right`` is invalid.
    """
    _check_right(right)
    s, k, t, r, q = _check_market(spot, strike, years, rate, dividend_yield)
    p = _array(price, "price")
    s, k, t, r, q, p = (
        np.asarray(a, dtype=np.float64) for a in np.broadcast_arrays(s, k, t, r, q, p)
    )
    r_c = np.log1p(r)
    q_c = np.log1p(q)
    is_call = right == "C"
    lower, upper = _bounds(s, k, t, r_c, q_c, is_call)
    valid = np.isfinite(p) & (p > lower) & (p < upper)
    lo = np.full(p.shape, VOL_MIN)
    hi = np.full(p.shape, VOL_MAX)
    valid &= (_price(s, k, t, r_c, q_c, lo, is_call) <= p) & (
        p <= _price(s, k, t, r_c, q_c, hi, is_call)
    )
    for _ in range(MAX_ITER):
        mid = 0.5 * (lo + hi)
        above = _price(s, k, t, r_c, q_c, mid, is_call) > p
        hi = np.where(above, mid, hi)
        lo = np.where(above, lo, mid)
        if np.max((hi - lo)[valid], initial=0.0) <= VOL_TOL:
            break
    return np.asarray(np.where(valid, 0.5 * (lo + hi), np.nan), dtype=np.float64)


def put_call_parity_forward(
    call_mid: float, put_mid: float, strike: float, years: float, rate: float
) -> float:
    """Return the forward price implied by one call and put at the same strike.

    By put-call parity ``C - P = D * (F - K)`` with ``D = (1 + rate) ** -years``, so
    ``F = K + (C - P) * (1 + rate) ** years``.

    Args:
        call_mid: Call mid price in dollars per share.
        put_mid: Put mid price in dollars per share.
        strike: Shared strike in dollars; must be positive.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.

    Returns:
        Implied forward price of the underlying in dollars.

    Raises:
        EngineInputError: If any input is non-finite or out of range.
    """
    values = as_float_1d([call_mid, put_mid, strike, years, rate], "parity inputs")
    c, p, k, t, r = (float(v) for v in values)
    if k <= 0:
        raise EngineInputError("strike must be positive")
    if t <= 0:
        raise EngineInputError("years must be positive")
    if r <= -1:
        raise EngineInputError("rate must be greater than -1")
    return float(k + (c - p) * (1.0 + r) ** t)


def implied_forward(
    strikes: npt.ArrayLike,
    call_mids: npt.ArrayLike,
    put_mids: npt.ArrayLike,
    *,
    years: float,
    rate: float,
) -> float:
    """Return the forward implied by a chain, using the strikes nearest at-the-money.

    The up to three strikes with the smallest ``|call - put|`` (closest to the forward)
    each give a parity forward; the median of those is returned.

    Args:
        strikes: Strikes in dollars, strictly increasing and positive.
        call_mids: Call mid prices in dollars per share, one per strike.
        put_mids: Put mid prices in dollars per share, one per strike.
        years: Time to expiry in years; must be positive.
        rate: Risk-free APY as a decimal; must exceed -1.

    Returns:
        Implied forward price of the underlying in dollars.

    Raises:
        EngineInputError: If the arrays differ in length, are empty, strikes are not
            strictly increasing and positive, or a scalar is out of range.
    """
    k = as_float_1d(strikes, "strikes")
    c = as_float_1d(call_mids, "call_mids")
    p = as_float_1d(put_mids, "put_mids")
    require_same_length(k, c, ("strikes", "call_mids"))
    require_same_length(k, p, ("strikes", "put_mids"))
    require_strictly_increasing(k, "strikes")
    if k[0] <= 0:
        raise EngineInputError("strikes must be positive")
    nearest = np.argsort(np.abs(c - p), kind="stable")[:3]
    forwards = [
        put_call_parity_forward(float(c[i]), float(p[i]), float(k[i]), years, rate) for i in nearest
    ]
    return float(np.median(forwards))
