"""Historical daily prices from the DoltHub ``post-no-preference/stocks`` database.

DoltHub serves free end-of-day OHLCV bars (the ``ohlcv`` table) through the same SQL over
HTTP API as the option chains. This module turns a set of symbols and a date range into a
validated ``bronze.underlying_price`` frame:

1. ``oap.calendar.trading_days`` lists the session days, so holidays are never queried.
2. ``month_chunks`` groups them by calendar month. One query per month carries **all** the
   symbols (``act_symbol IN (...) AND date IN (...)``): a month for the whole watchlist is
   a couple of hundred rows and answers in seconds, while a year-long list or an aggregate
   such as ``MIN(date)`` exceeds DoltHub's time limit. Do not widen the list beyond a month.
3. ``DoltHubClient.query_pages`` pages each month with ``LIMIT 1000 OFFSET n``.
4. ``parse_price_rows`` maps the string-typed rows to the bronze price contract, and the
   result is validated with ``PRICE_FRAME``.

The network boundary is ``DoltHubClient``; ``build_price_query`` and ``parse_price_rows`` are
pure. Prices are US dollars per share **as traded, not adjusted** for splits or dividends,
and volume is shares (see ``oap.ingest.price_schema``). DoltHub commits the bars of a session
at about 05:30 UTC on the next day, so a range ending today is missing its last session.

One security can hide behind two tickers: before the FB to META rename (2022-06-09), ``META``
in this database is a different instrument, the Roundhill Metaverse ETF. Those rows are
stored as received; join prices to chains on ``(underlying, trade_date)`` rather than
trusting a price row to belong to the issuer.
"""

import functools
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pandas as pd

from oap.calendar import trading_days
from oap.ingest.dolthub import (
    DOLTHUB_STOCKS_URL,
    PAGE_SIZE,
    SYMBOL_PATTERN,
    DoltHubClient,
    month_chunks,
    optional_float,
    required_text,
)
from oap.ingest.price_schema import PRICE_FRAME, PRICE_SCHEMA
from oap.ingest.schema import frame_from_records, utc_instant

logger = logging.getLogger(__name__)

SOURCE = "dolthub_stocks"
"""Value of ``source`` on every row this module produces."""

_COLUMNS = ("date", "act_symbol", "open", "high", "low", "close", "volume")


def stocks_client(http: httpx.Client | None = None, **kwargs: Any) -> DoltHubClient:
    """Create a DoltHub client for the ``stocks`` database.

    Args:
        http: Client to send requests with; tests pass one built on ``httpx.MockTransport``.
        **kwargs: Passed to ``DoltHubClient`` (``page_pause_s``, ``retry_wait``,
            ``max_attempts``).

    Returns:
        A client whose base URL is ``DOLTHUB_STOCKS_URL``.
    """
    return DoltHubClient(http, base_url=DOLTHUB_STOCKS_URL, **kwargs)


def build_price_query(symbols: Sequence[str], dates: Sequence[date], offset: int) -> str:
    """Build one page of the ``ohlcv`` query for a set of symbols on a set of dates.

    The query selects ``date, act_symbol, open, high, low, close, volume`` for
    ``act_symbol IN (symbols) AND date IN (dates)``, ordered by the table's primary key
    ``(date, act_symbol)`` so pages are stable, and ends with ``LIMIT 1000 OFFSET offset``.
    Symbols and dates are de-duplicated and sorted.

    Args:
        symbols: Tickers: 1 to 6 characters from ``A-Z``, digits, ``.`` and ``-``, starting
            with a letter.
        dates: Trade dates to include; order does not matter.
        offset: Number of rows to skip, a multiple of ``PAGE_SIZE`` in practice.

    Returns:
        The SQL text, ready to pass as the ``q`` query parameter.

    Raises:
        ValueError: If ``symbols`` or ``dates`` is empty, ``offset`` is negative, or a symbol
            is not of the form above (the value is interpolated into SQL, so nothing else is
            allowed).
    """
    if not symbols:
        raise ValueError("symbols must not be empty")
    if not dates:
        raise ValueError("dates must not be empty")
    if offset < 0:
        raise ValueError(f"offset must not be negative, got {offset}")
    for symbol in symbols:
        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError(f"unsafe or malformed symbol: {symbol!r}")
    symbol_list = ", ".join(f"'{symbol}'" for symbol in sorted(set(symbols)))
    date_list = ", ".join(f"'{d.isoformat()}'" for d in sorted(set(dates)))
    return (
        f"SELECT {', '.join(_COLUMNS)} FROM ohlcv"
        f" WHERE act_symbol IN ({symbol_list}) AND date IN ({date_list})"
        f" ORDER BY date, act_symbol"
        f" LIMIT {PAGE_SIZE} OFFSET {offset}"
    )


def _parse_row(row: Mapping[str, str | None], ingested_at: datetime) -> dict[str, Any]:
    """Map one DoltHub ``ohlcv`` row to a bronze price record."""
    volume = row.get("volume")
    return {
        "trade_date": date.fromisoformat(required_text(row, "date")),
        "underlying": required_text(row, "act_symbol"),
        "open": optional_float(row, "open"),
        "high": optional_float(row, "high"),
        "low": optional_float(row, "low"),
        "close": optional_float(row, "close"),
        "volume": None if volume is None or volume == "" else _volume(volume),
        "source": SOURCE,
        "ingested_at": ingested_at,
    }


def _volume(text: str) -> int:
    """Parse a share count, which DoltHub sends as an integer string."""
    try:
        return int(text)
    except ValueError as e:
        raise ValueError(f"column 'volume' is not an integer: {text!r}") from e


def _inconsistent(record: Mapping[str, Any]) -> bool:
    """Say whether a bar breaks ``high >= low`` or has a close outside [low, high]."""
    high, low, close = record["high"], record["low"], record["close"]
    if high is not None and low is not None and high < low:
        return True
    return (high is not None and close > high) or (low is not None and close < low)


def _open_outside(record: Mapping[str, Any]) -> bool:
    """Say whether a bar's open lies outside [low, high], where those are present."""
    open_, high, low = record["open"], record["high"], record["low"]
    if open_ is None:
        return False
    return (high is not None and open_ > high) or (low is not None and open_ < low)


def parse_price_rows(
    rows: Sequence[Mapping[str, str | None]], *, ingested_at: datetime
) -> pd.DataFrame:
    """Map DoltHub ``ohlcv`` rows to a bronze price frame.

    Every DoltHub value arrives as a string or null. ``date`` becomes ``trade_date``,
    ``act_symbol`` becomes ``underlying``, prices become floats in dollars per share (as
    traded), volume becomes an integer share count and ``source`` is ``"dolthub_stocks"``.
    Rows are then cleaned, each step logging a WARNING with the count per underlying:

    * rows without a close are dropped;
    * rows repeating an ``(underlying, trade_date)`` already seen are dropped, keeping the
      first;
    * rows whose high is below their low, or whose close lies outside [low, high] where those
      are present, are dropped;
    * rows whose open lies outside [low, high] are **kept** (the bronze contract does not
      check open) and only counted.

    The frame is not validated; the caller runs ``PRICE_FRAME.validate``.

    Args:
        rows: The ``rows`` array of one or more DoltHub responses.
        ingested_at: Timezone-aware instant stamped on every row, stored in UTC.

    Returns:
        A frame with PRICE_SCHEMA's columns and dtypes; empty for no rows.

    Raises:
        ValueError: If ``ingested_at`` is naive, or a row lacks its date or symbol or holds a
            value that does not parse.
    """
    stamp = utc_instant(ingested_at)
    records: dict[tuple[str, date], dict[str, Any]] = {}
    no_close: Counter[str] = Counter()
    for row in rows:
        record = _parse_row(row, stamp)
        if record["close"] is None:
            no_close[record["underlying"]] += 1
            continue
        records.setdefault((record["underlying"], record["trade_date"]), record)
    for underlying, count in sorted(no_close.items()):
        logger.warning("dolthub_stocks: dropped %d rows without a close for %s", count, underlying)

    kept: list[dict[str, Any]] = []
    inconsistent: Counter[str] = Counter()
    open_outside: Counter[str] = Counter()
    for record in records.values():
        if _inconsistent(record):
            inconsistent[record["underlying"]] += 1
            continue
        if _open_outside(record):
            open_outside[record["underlying"]] += 1
        kept.append(record)
    for underlying, count in sorted(inconsistent.items()):
        logger.warning(
            "dolthub_stocks: dropped %d rows with inconsistent OHLC for %s", count, underlying
        )
    for underlying, count in sorted(open_outside.items()):
        logger.warning(
            "dolthub_stocks: kept %d rows with open outside [low, high] for %s", count, underlying
        )
    return frame_from_records(kept, PRICE_SCHEMA)


def fetch_prices(
    symbols: Sequence[str],
    start: date,
    end: date,
    *,
    client: DoltHubClient,
    ingested_at: datetime | None = None,
) -> pd.DataFrame:
    """Fetch and validate daily bars for a set of symbols over a date range.

    Queries only NYSE session days in ``[start, end]``, one month per query with all the
    symbols, paging each month as described in the module docstring, then parses and
    validates the union. Logs one INFO line per month with its row count.

    Args:
        symbols: Tickers, for example ``["SPY", "qqq"]``; upper-cased and de-duplicated.
        start: First trade date, inclusive.
        end: Last trade date, inclusive.
        client: DoltHub client for the stocks database (see ``stocks_client``).
        ingested_at: UTC instant stamped on every row; the current time when omitted.

    Returns:
        A frame that passed ``PRICE_FRAME.validate(frame, lazy=True)``, with
        ``source == "dolthub_stocks"``; empty when DoltHub holds no rows for the range.
        Symbols DoltHub has no bars for simply contribute no rows.

    Raises:
        ValueError: If ``symbols`` is empty, a symbol is malformed, or ``start`` is after
            ``end``.
        DoltHubError: If a query fails (see ``DoltHubClient.query``).
        pandera.errors.SchemaErrors: If the parsed rows break the bronze contract; validation
            is lazy, so every failed check is listed.
    """
    tickers = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    if not tickers:
        raise ValueError("symbols must not be empty")
    bad = [symbol for symbol in tickers if not SYMBOL_PATTERN.fullmatch(symbol)]
    if bad:
        raise ValueError(f"unsafe or malformed symbols: {bad}")
    sessions = trading_days(start, end)
    stamp = ingested_at if ingested_at is not None else datetime.now(UTC)
    rows: list[dict[str, str | None]] = []
    for month in month_chunks(sessions):
        month_rows = client.query_pages(functools.partial(build_price_query, tickers, month))
        logger.info(
            "dolthub_stocks %s: %d rows for %d symbols over %d sessions",
            f"{month[0]:%Y-%m}",
            len(month_rows),
            len(tickers),
            len(month),
        )
        rows.extend(month_rows)
    frame = parse_price_rows(rows, ingested_at=stamp)
    return PRICE_FRAME.validate(frame, lazy=True)
