"""Deterministic builders of bronze frames and DoltHub rows for tests.

Built independently of the code under test: OCC symbols are formatted here with an f-string,
and frames go straight from Python values through BRONZE_SCHEMA to pyarrow-backed pandas.
"""

import random
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pyarrow as pa

from oap.ingest.schema import BRONZE_SCHEMA

INGESTED_AT = datetime(2024, 1, 2, 22, 0, tzinfo=UTC)


def occ(underlying: str, expiration: date, right: str, strike: Decimal) -> str:
    return f"{underlying}{expiration:%y%m%d}{right}{int(strike * 1000):08d}"


def bronze_frame(
    trade_date: date,
    *,
    underlyings: Sequence[str] = ("SPY",),
    rows_per_underlying: int = 10,
    source: str = "dolthub",
    seed: int = 0,
    ingested_at: datetime = INGESTED_AT,
) -> pd.DataFrame:
    """A valid bronze frame: unique contracts, uncrossed quotes, future expirations."""
    rng = random.Random(seed)
    records: list[dict[str, object]] = []
    for underlying in underlyings:
        for i in range(rows_per_underlying):
            right = "CP"[i % 2]
            strike = Decimal(100 + i // 2) + Decimal("0.50") * (i % 4 // 2)
            expiration = trade_date + timedelta(days=7 * (1 + i % 3))
            bid = round(rng.uniform(0.05, 20.0), 2)
            ask = round(bid + rng.uniform(0.01, 1.0), 2)
            records.append(
                {
                    "trade_date": trade_date,
                    "underlying": underlying,
                    "occ_symbol": occ(underlying, expiration, right, strike),
                    "expiration": expiration,
                    "strike": strike,
                    "right": right,
                    "bid": bid,
                    "ask": ask,
                    "last": None if source == "dolthub" else round((bid + ask) / 2, 2),
                    "volume": None if source == "dolthub" else rng.randint(0, 5000),
                    "open_interest": None,
                    "iv": round(rng.uniform(0.05, 1.5), 4),
                    "delta": round(rng.uniform(-1, 1), 4),
                    "gamma": round(rng.uniform(0, 0.1), 4),
                    "theta": round(rng.uniform(-1, 0), 4),
                    "vega": round(rng.uniform(0, 1), 4),
                    "rho": round(rng.uniform(-1, 1), 4),
                    "underlying_price": None if source == "dolthub" else 470.0,
                    "source": source,
                    "ingested_at": ingested_at,
                }
            )
    table = pa.Table.from_pylist(records, schema=BRONZE_SCHEMA)
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def dolthub_row(
    *,
    trade_date: str = "2024-01-02",
    symbol: str = "SPY",
    expiration: str = "2024-01-19",
    strike: str = "470.00",
    call_put: str = "Call",
    bid: str | None = "1.10",
    ask: str | None = "1.20",
    vol: str | None = "0.1500",
    delta: str | None = "0.5000",
    gamma: str | None = "0.0100",
    theta: str | None = "-0.2000",
    vega: str | None = "0.3000",
    rho: str | None = "0.0400",
) -> dict[str, str | None]:
    """One ``option_chain`` row as DoltHub's SQL API returns it: every value a string."""
    return {
        "date": trade_date,
        "act_symbol": symbol,
        "expiration": expiration,
        "strike": strike,
        "call_put": call_put,
        "bid": bid,
        "ask": ask,
        "vol": vol,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
    }


def dolthub_rows(
    n: int, *, trade_date: str = "2024-01-02", start: int = 0
) -> list[dict[str, str | None]]:
    """``n`` distinct contracts on one date, numbered from ``start``."""
    return [
        dolthub_row(
            trade_date=trade_date,
            strike=f"{1 + (start + i) // 2}.00",
            call_put="Call" if (start + i) % 2 == 0 else "Put",
        )
        for i in range(n)
    ]
