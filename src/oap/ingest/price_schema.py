"""The bronze underlying price contract: one daily OHLCV bar per underlying per source.

A bronze price row is one underlying's open, high, low, close and volume for one trade
date as one source reported it. The natural key is ``(underlying, trade_date, source)``.
The only source today is DoltHub's ``stocks`` database (``dolthub_stocks``).

Units: open, high, low and close are US dollars per share **as traded on that date, not
adjusted for splits or dividends** (AAPL closed 499.23 on 2020-08-28 and 129.04 on
2020-08-31, across its 4-for-1 split). That is the price option strikes on the same date
are quoted against; a return series needs the split table applied downstream. Volume is
shares. ``trade_date`` is the exchange calendar date; ``ingested_at`` is the UTC instant of
the load.

Two representations of the same row live here, mirroring ``oap.ingest.schema``:

* ``PRICE_SCHEMA`` is the Arrow schema written to Iceberg.
* ``PRICE_FRAME`` is the pandera schema every ingest path validates against before writing.
  Frames are pandas DataFrames with pyarrow-backed columns (``pd.ArrowDtype``).

``PRICE_FRAME`` requires ``high >= low`` and ``low <= close <= high`` wherever the values are
present. It deliberately does not constrain ``open``: the vendor holds a row whose open lies
outside its range (IWM on 2021-05-05 opened at 224.28 against a high of 224.16), and
rejecting it would fail the whole month's write. Open is stored as received and the parser
logs a warning when it is out of range.

Everything in this module is pure: no I/O, no clocks.
"""

from collections.abc import Mapping
from typing import Any

import pandas as pd
import pandera.pandas as pa_schema
import pyarrow as pa

PRICE_SOURCES: frozenset[str] = frozenset({"dolthub_stocks"})
"""Every value ``source`` may take on a price row: one per vendor feed."""

PRICE_KEY_COLUMNS: tuple[str, str, str] = ("underlying", "trade_date", "source")
"""The natural key of a bronze price row."""

_PRICE_FIELDS: "list[pa.Field[Any]]" = [
    pa.field("trade_date", pa.date32(), nullable=False),
    pa.field("underlying", pa.string(), nullable=False),
    pa.field("open", pa.float64()),
    pa.field("high", pa.float64()),
    pa.field("low", pa.float64()),
    pa.field("close", pa.float64(), nullable=False),
    pa.field("volume", pa.int64()),
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingested_at", pa.timestamp("us", tz="UTC"), nullable=False),
]

PRICE_SCHEMA: pa.Schema = pa.schema(_PRICE_FIELDS)
"""Arrow schema of ``bronze.underlying_price``, in column order (units: module docstring)."""

_COLUMN_CHECKS: Mapping[str, list[pa_schema.Check]] = {
    "close": [pa_schema.Check.gt(0, error="close must be positive")],
    "volume": [pa_schema.Check.ge(0, error="volume must not be negative")],
    "source": [
        pa_schema.Check.isin(sorted(PRICE_SOURCES), error="source must be a known price feed")
    ],
}


def _high_not_below_low(frame: pd.DataFrame) -> pd.Series:
    """Row-wise: the bar's high is not below its low, or one side is missing."""
    return (frame["high"] >= frame["low"]).fillna(True).astype(bool)


def _close_within_low_high(frame: pd.DataFrame) -> pd.Series:
    """Row-wise: the close lies between the low and the high, where those are present."""
    above_low = (frame["close"] >= frame["low"]).fillna(True).astype(bool)
    below_high = (frame["close"] <= frame["high"]).fillna(True).astype(bool)
    return above_low & below_high


PRICE_FRAME: pa_schema.DataFrameSchema = pa_schema.DataFrameSchema(
    columns={
        field.name: pa_schema.Column(
            pd.ArrowDtype(field.type),
            checks=_COLUMN_CHECKS.get(field.name, []),
            nullable=field.nullable,
        )
        for field in PRICE_SCHEMA
    },
    checks=[
        pa_schema.Check(
            _high_not_below_low,
            name="high_not_below_low",
            error="high must not be below low when both are present",
        ),
        pa_schema.Check(
            _close_within_low_high,
            name="close_within_low_high",
            error="close must lie between low and high where those are present",
        ),
    ],
    unique=list(PRICE_KEY_COLUMNS),
    coerce=True,
    strict=True,
    ordered=True,
    name="bronze_underlying_price",
)
"""pandera contract for a bronze price frame: PRICE_SCHEMA's columns, order, nullability and
dtypes (as ``pd.ArrowDtype``), plus close > 0, volume >= 0, source in PRICE_SOURCES,
high >= low and low <= close <= high where present, and a unique
``(underlying, trade_date, source)`` key. ``open`` is not range-checked (see the module
docstring). Validation coerces dtypes and rejects extra columns.
"""
