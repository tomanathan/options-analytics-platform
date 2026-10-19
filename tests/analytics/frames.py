"""Synthetic frames for the analytics tests, priced with the engine's Black-Scholes.

Strikes and prices are in dollars per share, volatility is a decimal, time is in years and
rates are decimal APYs. Dates are ``datetime64`` columns, as DuckDB's ``.df()`` returns.
"""

from collections.abc import Iterable, Sequence
from datetime import date

import numpy as np
import pandas as pd

from oap.analytics.sample import PREDICTION_COLUMNS
from oap.engine.black_scholes import call_price, put_price

QUOTE_HALF_SPREAD = 0.05


def lognormal_quotes(
    underlying: str,
    trade_date: date,
    expiration: date,
    close: float,
    vol: float,
    rate: float,
    strikes: Iterable[float],
) -> pd.DataFrame:
    """Return one snapshot's chain with Black-Scholes mids and bid/ask = mid -/+ 0.05.

    Args:
        underlying: Ticker symbol.
        trade_date: Quote date.
        expiration: Expiration date.
        close: Underlying close in dollars.
        vol: Volatility as a decimal.
        rate: Risk-free APY as a decimal.
        strikes: Strikes in dollars.

    Returns:
        Put and call rows with the quote columns the analytics code reads.
    """
    k = np.asarray(list(strikes), dtype=np.float64)
    days = (expiration - trade_date).days
    years = days / 365
    frames = []
    for right, price in (("P", put_price), ("C", call_price)):
        mid = price(close, k, years, rate, vol)
        frames.append(
            pd.DataFrame(
                {
                    "underlying": underlying,
                    "trade_date": pd.Timestamp(trade_date),
                    "expiration": pd.Timestamp(expiration),
                    "strike": k,
                    "option_right": right,
                    "bid": mid - QUOTE_HALF_SPREAD,
                    "ask": mid + QUOTE_HALF_SPREAD,
                    "underlying_close": close,
                    "dte_days": days,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def outcomes_frame(rows: Sequence[tuple[str, date, date, float]]) -> pd.DataFrame:
    """Build an expiration outcomes frame.

    Args:
        rows: ``(underlying, expiration, settlement_date, settlement_close)`` tuples,
            with the close in dollars.

    Returns:
        Frame with ``datetime64`` dates.
    """
    frame = pd.DataFrame(
        rows, columns=["underlying", "expiration", "settlement_date", "settlement_close"]
    )
    frame["expiration"] = pd.to_datetime(frame["expiration"])
    frame["settlement_date"] = pd.to_datetime(frame["settlement_date"])
    frame["settlement_close"] = frame["settlement_close"].astype("float64")
    return frame


def daily_frame(rows: Sequence[tuple[str, date, float]]) -> pd.DataFrame:
    """Build a daily log return frame.

    Args:
        rows: ``(underlying, trade_date, log_return)`` tuples; the log return is a
            dimensionless decimal.

    Returns:
        Frame with a ``datetime64`` trade date.
    """
    frame = pd.DataFrame(rows, columns=["underlying", "trade_date", "log_return"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame["log_return"] = frame["log_return"].astype("float64")
    return frame


def synthetic_predictions(
    years: Sequence[int], per_year: int, *, seed: int = 7, realised_rate: float = 0.3
) -> pd.DataFrame:
    """Build prediction rows directly, without option chains.

    Each year has ``per_year`` rows with trade dates in that year and expirations 30 days
    later (so late-year trades expire in the next year). Raw probabilities are uniform in
    (0, 1) and outcomes occur with probability ``p * realised_rate / 0.5`` clipped, which
    makes the raw probabilities miscalibrated on purpose.

    Args:
        years: Calendar years of the trade dates.
        per_year: Number of rows per year.
        seed: Seed of the random generator.
        realised_rate: Realised frequency at a raw probability of 0.5, a decimal.

    Returns:
        Frame with ``PREDICTION_COLUMNS``, sorted by trade date.
    """
    rng = np.random.default_rng(seed)
    parts = []
    for year in years:
        offsets = rng.integers(0, 365, size=per_year)
        trade = pd.Timestamp(date(year, 1, 1)) + pd.to_timedelta(offsets, unit="D")
        p = rng.uniform(0.02, 0.98, size=per_year)
        y = rng.uniform(size=per_year) < np.clip(p * realised_rate / 0.5, 0.0, 1.0)
        parts.append(
            pd.DataFrame(
                {
                    "underlying": rng.choice(["AAA", "BBB"], size=per_year),
                    "trade_date": trade,
                    "expiration": trade + pd.Timedelta(days=30),
                    "settlement_date": trade + pd.Timedelta(days=30),
                    "dte_days": 30,
                    "dte_years": 30 / 365,
                    "dte_bucket": "21-35d",
                    "fold": year,
                    "moneyness": 0.95,
                    "target_strike": 95.0,
                    "underlying_close": 100.0,
                    "settlement_close": np.where(y, 90.0, 110.0),
                    "predicted_raw": p,
                    "realised": y,
                    "n_knots": 20,
                    "forward": 100.0,
                    "cdf_flags": "",
                }
            )
        )
    frame = pd.concat(parts, ignore_index=True).sort_values("trade_date", kind="stable")
    return frame.reset_index(drop=True)[list(PREDICTION_COLUMNS)]
