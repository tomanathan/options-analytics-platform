"""Deterministic builders of bronze price frames and DoltHub ``ohlcv`` rows for tests."""

import random
from collections.abc import Sequence
from datetime import UTC, date, datetime

import pandas as pd
import pyarrow as pa

from oap.ingest.price_schema import PRICE_SCHEMA

INGESTED_AT = datetime(2024, 1, 3, 6, 0, tzinfo=UTC)


def price_frame(
    trade_date: date,
    underlyings: Sequence[str] = ("SPY",),
    seed: int = 0,
    *,
    source: str = "dolthub_stocks",
    ingested_at: datetime = INGESTED_AT,
) -> pd.DataFrame:
    """A valid bronze price frame: one bar per underlying, low <= open/close <= high."""
    rng = random.Random(seed)
    records: list[dict[str, object]] = []
    for underlying in underlyings:
        low = round(rng.uniform(50.0, 400.0), 2)
        high = round(low + rng.uniform(0.5, 10.0), 2)
        records.append(
            {
                "trade_date": trade_date,
                "underlying": underlying,
                "open": round((low + high) / 2, 2),
                "high": high,
                "low": low,
                "close": round(low + (high - low) * rng.random(), 2),
                "volume": rng.randint(1_000, 90_000_000),
                "source": source,
                "ingested_at": ingested_at,
            }
        )
    table = pa.Table.from_pylist(records, schema=PRICE_SCHEMA)
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def ohlcv_row(
    *,
    trade_date: str = "2024-01-05",
    symbol: str = "SPY",
    open_: str | None = "468.04",
    high: str | None = "470.44",
    low: str | None = "466.43",
    close: str | None = "467.92",
    volume: str | None = "86118913",
) -> dict[str, str | None]:
    """One DoltHub ``ohlcv`` row as the API returns it: every value a string or null."""
    return {
        "date": trade_date,
        "act_symbol": symbol,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }
