"""The bronze option chain contract: one schema shared by every source and the writer.

A bronze row is one option contract on one trade date as one source reported it. DoltHub
history and Alpaca snapshots both land in the same table, told apart by ``source``, so the
same contract on the same date can be held once per source. The natural key is
``(occ_symbol, trade_date, source)``.

Three representations of the same contract live here:

* ``BRONZE_SCHEMA`` is the Arrow schema written to Iceberg.
* ``BRONZE_FRAME`` is the pandera schema every ingest path validates against before writing.
  Frames are pandas DataFrames whose columns are pyarrow-backed (``pd.ArrowDtype``) so that
  dates stay dates, strikes stay exact decimals and nulls stay nulls on the way to Arrow.
* ``occ_symbol`` and ``parse_occ_symbol`` convert between contract terms and the OCC symbol.

Units: strikes, bids, asks, last prices and the underlying price are US dollars per share;
implied volatility is a decimal (0.20 means 20%); greeks are as the vendor reports them per
share (theta per calendar day); volume and open interest are contracts. ``trade_date`` and
``expiration`` are exchange calendar dates; ``ingested_at`` is the UTC instant of the load.

The strike is ``decimal(10, 3)``: the OCC symbol encodes strikes in thousandths of a dollar,
and adjusted contracts after splits and special dividends carry three decimals (12.625), so
two decimals would reject real contracts.

Everything in this module is pure: no I/O, no clocks.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import pandera.pandas as pa_schema
import pyarrow as pa

SOURCES: frozenset[str] = frozenset({"dolthub", "alpaca_indicative"})
"""Every value ``source`` may take: one per vendor feed that lands in bronze."""

KEY_COLUMNS: tuple[str, str, str] = ("occ_symbol", "trade_date", "source")
"""The natural key of a bronze row."""

RIGHTS: frozenset[str] = frozenset({"C", "P"})
"""Option rights: ``C`` for a call, ``P`` for a put."""

_ROOT = re.compile(r"[A-Z][A-Z0-9]{0,5}")
_OCC = re.compile(r"([A-Z][A-Z0-9]{0,5}) *(\d{6})([CP])(\d{8})")
_MAX_THOUSANDTHS = 10**8

_BRONZE_FIELDS: "list[pa.Field[Any]]" = [
    pa.field("trade_date", pa.date32(), nullable=False),
    pa.field("underlying", pa.string(), nullable=False),
    pa.field("occ_symbol", pa.string(), nullable=False),
    pa.field("expiration", pa.date32(), nullable=False),
    pa.field("strike", pa.decimal128(10, 3), nullable=False),
    pa.field("right", pa.string(), nullable=False),
    pa.field("bid", pa.float64()),
    pa.field("ask", pa.float64()),
    pa.field("last", pa.float64()),
    pa.field("volume", pa.int64()),
    pa.field("open_interest", pa.int64()),
    pa.field("iv", pa.float64()),
    pa.field("delta", pa.float64()),
    pa.field("gamma", pa.float64()),
    pa.field("theta", pa.float64()),
    pa.field("vega", pa.float64()),
    pa.field("rho", pa.float64()),
    pa.field("underlying_price", pa.float64()),
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingested_at", pa.timestamp("us", tz="UTC"), nullable=False),
]

BRONZE_SCHEMA: pa.Schema = pa.schema(_BRONZE_FIELDS)
"""Arrow schema of ``bronze.option_chain``, in column order. See the module docstring for units."""

_COLUMN_CHECKS: Mapping[str, list[pa_schema.Check]] = {
    "strike": [pa_schema.Check.gt(0, error="strike must be positive")],
    "right": [pa_schema.Check.isin(sorted(RIGHTS), error="right must be C or P")],
    "source": [pa_schema.Check.isin(sorted(SOURCES), error="source must be a known feed")],
}


def _expiration_not_before_trade_date(frame: pd.DataFrame) -> pd.Series:
    """Row-wise: the contract had not expired on the trade date."""
    return frame["expiration"] >= frame["trade_date"]


def _bid_not_above_ask(frame: pd.DataFrame) -> pd.Series:
    """Row-wise: the quote is not crossed, or one side is missing."""
    return (frame["bid"] <= frame["ask"]).fillna(True).astype(bool)


BRONZE_FRAME: pa_schema.DataFrameSchema = pa_schema.DataFrameSchema(
    columns={
        field.name: pa_schema.Column(
            pd.ArrowDtype(field.type),
            checks=_COLUMN_CHECKS.get(field.name, []),
            nullable=field.nullable,
        )
        for field in BRONZE_SCHEMA
    },
    checks=[
        pa_schema.Check(
            _expiration_not_before_trade_date,
            name="expiration_not_before_trade_date",
            error="expiration must be on or after trade_date",
        ),
        pa_schema.Check(
            _bid_not_above_ask,
            name="bid_not_above_ask",
            error="bid must not exceed ask when both are present",
        ),
    ],
    unique=list(KEY_COLUMNS),
    coerce=True,
    strict=True,
    ordered=True,
    name="bronze_option_chain",
)
"""pandera contract for a bronze frame: BRONZE_SCHEMA's columns, order, nullability and dtypes
(as ``pd.ArrowDtype``), plus right in {C, P}, strike > 0, source in SOURCES,
expiration >= trade_date, bid <= ask where both are present, and a unique
``(occ_symbol, trade_date, source)`` key. Validation coerces dtypes and rejects extra columns.
"""


def occ_symbol(underlying: str, expiration: date, right: str, strike: Decimal) -> str:
    """Build the compact OCC option symbol for a contract.

    The OCC format is the root symbol, the expiration as ``yymmdd``, ``C`` or ``P``, and the
    strike in thousandths of a dollar zero-padded to eight digits. OCC pads the root to six
    characters with spaces; the compact form used throughout oap (and by Alpaca) drops them.

    Args:
        underlying: Root symbol, 1 to 6 upper-case characters, for example ``"SPY"``.
        expiration: Expiration date of the contract.
        right: ``"C"`` for a call or ``"P"`` for a put.
        strike: Strike in dollars, positive, with at most three decimal places and below
            100,000.

    Returns:
        The compact symbol, for example ``"SPY240119C00470000"`` for the SPY 2024-01-19
        470-dollar call.

    Raises:
        ValueError: If any argument cannot be represented in the OCC format.
    """
    if not _ROOT.fullmatch(underlying):
        raise ValueError(f"underlying must be 1-6 upper-case characters, got {underlying!r}")
    if right not in RIGHTS:
        raise ValueError(f"right must be C or P, got {right!r}")
    if not 2000 <= expiration.year <= 2099:
        raise ValueError(f"expiration year must be in 2000-2099, got {expiration}")
    if not strike.is_finite() or strike <= 0:
        raise ValueError(f"strike must be a positive amount, got {strike}")
    thousandths = strike * 1000
    if thousandths != thousandths.to_integral_value() or thousandths >= _MAX_THOUSANDTHS:
        raise ValueError(f"strike {strike} does not fit the OCC strike field")
    return f"{underlying}{expiration:%y%m%d}{right}{int(thousandths):08d}"


def parse_occ_symbol(symbol: str) -> tuple[str, date, str, Decimal]:
    """Split an OCC option symbol into its contract terms; the inverse of ``occ_symbol``.

    Accepts both the compact form and the space-padded OCC form.

    Args:
        symbol: OCC symbol, for example ``"SPY240119C00470000"`` or
            ``"SPY   240119C00470000"``.

    Returns:
        ``(underlying, expiration, right, strike)`` with the strike in dollars as a Decimal,
        for example ``("SPY", date(2024, 1, 19), "C", Decimal("470"))``.

    Raises:
        ValueError: If ``symbol`` is not a well-formed OCC symbol.
    """
    match = _OCC.fullmatch(symbol)
    if match is None:
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    root, yymmdd, right, thousandths = match.groups()
    expiration = date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:]))
    return root, expiration, right, Decimal(int(thousandths)) / 1000


def empty_frame(schema: pa.Schema = BRONZE_SCHEMA) -> pd.DataFrame:
    """Return a bronze frame with no rows.

    Args:
        schema: Arrow schema of the table; the option chain's when omitted.

    Returns:
        A DataFrame with ``schema``'s columns in order, each with the matching
        ``pd.ArrowDtype``, that passes the table's pandera schema (``BRONZE_FRAME`` by
        default).
    """
    return schema.empty_table().to_pandas(types_mapper=pd.ArrowDtype)


def to_arrow(frame: pd.DataFrame, schema: pa.Schema = BRONZE_SCHEMA) -> pa.Table:
    """Convert a bronze frame to an Arrow table with exactly ``schema``.

    The frame is not validated here; callers validate with the table's pandera schema
    first. The index is dropped.

    Args:
        frame: A frame with ``schema``'s columns.
        schema: Arrow schema of the table; the option chain's when omitted.

    Returns:
        An Arrow table whose schema equals ``schema`` (names, types, nullability, order).

    Raises:
        pyarrow.ArrowInvalid: If a column cannot be cast to its ``schema`` type or a
            non-nullable column holds a null.
        KeyError: If a ``schema`` column is missing from the frame.
    """
    table = pa.Table.from_pandas(frame[schema.names], schema=schema, preserve_index=False)
    for field in schema:
        if not field.nullable and table.column(field.name).null_count:
            raise pa.ArrowInvalid(f"non-nullable column {field.name!r} holds nulls")
    return table.replace_schema_metadata(None)


def utc_instant(ingested_at: datetime) -> datetime:
    """Return a timezone-aware instant converted to UTC.

    Args:
        ingested_at: Load time; must carry a time zone.

    Returns:
        The same instant with ``tzinfo=UTC``.

    Raises:
        ValueError: If ``ingested_at`` is naive.
    """
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise ValueError(f"ingested_at must be timezone-aware, got {ingested_at!r}")
    return ingested_at.astimezone(UTC)


def split_crossed_quotes(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], Counter[tuple[str, date]]]:
    """Separate rows whose quote is crossed (bid above ask, both present) from the rest.

    Bronze keeps ``bid <= ask`` as an invariant, so parsers drop crossed rows and report how
    many they dropped. A locked quote (bid equal to ask) is kept.

    Args:
        records: Row dicts with ``underlying``, ``trade_date``, ``bid`` and ``ask`` keys;
            prices in dollars or None.

    Returns:
        ``(kept, dropped)``: the rows to keep, in their original order, and the number of
        dropped rows per ``(underlying, trade_date)``.
    """
    kept: list[Mapping[str, Any]] = []
    dropped: Counter[tuple[str, date]] = Counter()
    for record in records:
        bid, ask = record["bid"], record["ask"]
        if bid is not None and ask is not None and bid > ask:
            dropped[(record["underlying"], record["trade_date"])] += 1
        else:
            kept.append(record)
    return kept, dropped


def frame_from_records(
    records: Sequence[Mapping[str, Any]], schema: pa.Schema = BRONZE_SCHEMA
) -> pd.DataFrame:
    """Build a bronze-shaped frame from row dicts keyed by ``schema``'s column names.

    Missing keys become nulls. The frame is not validated.

    Args:
        records: One dict per row, values as Python objects (``date``, ``Decimal``,
            ``float``, ``int``, ``str``, timezone-aware ``datetime`` or None).
        schema: Arrow schema of the table; the option chain's when omitted.

    Returns:
        A frame with ``schema``'s columns and dtypes; ``empty_frame(schema)`` for no records.

    Raises:
        pyarrow.ArrowInvalid: If a value cannot be converted to its column type.
    """
    if not records:
        return empty_frame(schema)
    table = pa.Table.from_pylist(list(records), schema=schema)
    return table.to_pandas(types_mapper=pd.ArrowDtype)
