"""Historical option chains from the DoltHub ``post-no-preference/options`` database.

DoltHub serves a free end-of-day option chain history (``option_chain`` table) through a SQL
over HTTP API. This module turns a symbol and a date range into a validated bronze frame:

1. ``oap.calendar.trading_days`` lists the session days, so holidays are never queried.
2. ``month_chunks`` groups them by calendar month, one ``date IN (...)`` query per month.
   Range predicates on ``date`` time out on DoltHub; an explicit ``IN`` list does not.
3. Each month is paged with ``LIMIT 1000 OFFSET n`` (``build_query``), advancing the offset
   by the rows actually received. Paging stops on an empty page, or on a short page whose
   status is ``Success``. A full page reported as ``Success`` (what DoltHub returns when the
   query carries its own ``LIMIT``) and any ``RowLimit`` page, even a short one truncated by
   the server, continue the loop.
4. ``parse_rows`` maps the string-typed rows to the bronze contract, and the result is
   validated with ``BRONZE_FRAME``.

The network boundary is ``DoltHubClient``; ``build_query``, ``parse_rows`` and
``month_chunks`` are pure. DoltHub carries bid, ask, implied volatility and greeks only:
``last``, ``volume``, ``open_interest`` and ``underlying_price`` land as nulls. Prices are
dollars per share, implied volatility a decimal. A date with no rows is normal (coverage has
gaps) and is not an error.
"""

import functools
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import pandas as pd
from tenacity import RetryError, Retrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_base, wait_random_exponential

from oap.calendar import trading_days
from oap.ingest.schema import (
    BRONZE_FRAME,
    frame_from_records,
    occ_symbol,
    split_crossed_quotes,
    utc_instant,
)

logger = logging.getLogger(__name__)

DOLTHUB_BASE_URL = "https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master"
"""SQL read endpoint of the ``options`` database on its ``master`` branch."""

DOLTHUB_STOCKS_URL = "https://www.dolthub.com/api/v1alpha1/post-no-preference/stocks/master"
"""SQL read endpoint of the ``stocks`` database on its ``master`` branch."""

PAGE_SIZE = 1000
"""Rows per page; DoltHub returns at most 1000 rows per response."""

MAX_ATTEMPTS = 6
"""Attempts per query, including the first, before ``DoltHubClient.query`` gives up."""


SOURCE = "dolthub"
"""Value of ``source`` on every row this module produces."""

SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9.\-]{0,5}")
"""A well-formed ticker: 1 to 6 of ``A-Z``, digits, ``.`` and ``-``, starting with a letter.
Symbols are interpolated into SQL, so nothing else may reach a query."""

_COLUMNS = (
    "date",
    "act_symbol",
    "expiration",
    "strike",
    "call_put",
    "bid",
    "ask",
    "vol",
    "delta",
    "gamma",
    "theta",
    "vega",
    "rho",
)
_RIGHTS = {"Call": "C", "Put": "P"}
_GREEKS = ("delta", "gamma", "theta", "vega", "rho")


class DoltHubError(Exception):
    """DoltHub returned an error, or a retryable failure persisted past every attempt."""


class _RetryableError(Exception):
    """A failure worth another attempt: transport error, HTTP 429/5xx or a query timeout."""


def optional_float(row: Mapping[str, str | None], column: str) -> float | None:
    """Parse an optional decimal string column of a DoltHub row as a float.

    Args:
        row: A DoltHub row: column name to string or None.
        column: The column to read.

    Returns:
        The value, or None when the column is missing, null or empty.

    Raises:
        ValueError: If the value is present but not a number.
    """
    value = row.get(column)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError as e:
        raise ValueError(f"column {column!r} is not a number: {value!r}") from e


def required_text(row: Mapping[str, str | None], column: str) -> str:
    """Read a column of a DoltHub row that must be present.

    Args:
        row: A DoltHub row: column name to string or None.
        column: The column to read.

    Returns:
        The non-empty value.

    Raises:
        ValueError: If the column is missing, null or empty.
    """
    value = row.get(column)
    if value is None or value == "":
        raise ValueError(f"row lacks {column!r}: {dict(row)}")
    return value


def _parse_row(row: Mapping[str, str | None], ingested_at: datetime) -> dict[str, Any]:
    """Map one DoltHub row to a bronze record."""
    underlying = required_text(row, "act_symbol")
    call_put = required_text(row, "call_put")
    if call_put not in _RIGHTS:
        raise ValueError(f"unknown call_put {call_put!r}")
    right = _RIGHTS[call_put]
    trade_date = date.fromisoformat(required_text(row, "date"))
    expiration = date.fromisoformat(required_text(row, "expiration"))
    try:
        strike = Decimal(required_text(row, "strike"))
    except InvalidOperation as e:
        raise ValueError(f"strike is not a number: {row.get('strike')!r}") from e
    record: dict[str, Any] = {
        "trade_date": trade_date,
        "underlying": underlying,
        "occ_symbol": occ_symbol(underlying, expiration, right, strike),
        "expiration": expiration,
        "strike": strike,
        "right": right,
        "bid": optional_float(row, "bid"),
        "ask": optional_float(row, "ask"),
        "last": None,
        "volume": None,
        "open_interest": None,
        "iv": optional_float(row, "vol"),
        "underlying_price": None,
        "source": SOURCE,
        "ingested_at": ingested_at,
    }
    for greek in _GREEKS:
        record[greek] = optional_float(row, greek)
    return record


def build_query(symbol: str, dates: Sequence[date], offset: int) -> str:
    """Build one page of the option chain query for a symbol on a set of dates.

    The query selects every ``option_chain`` column for ``act_symbol = symbol`` and
    ``date IN (dates)``, ordered by the table's primary key
    (``date, expiration, strike, call_put``) so pages are stable, and ends with
    ``LIMIT 1000 OFFSET offset``.

    Args:
        symbol: Underlying ticker: 1 to 6 characters from ``A-Z``, digits, ``.`` and ``-``,
            starting with a letter.
        dates: Trade dates to include; order does not matter.
        offset: Number of rows to skip, a multiple of ``PAGE_SIZE`` in practice.

    Returns:
        The SQL text, ready to pass as the ``q`` query parameter.

    Raises:
        ValueError: If ``dates`` is empty, ``offset`` is negative, or ``symbol`` is not of the
            form above (the value is interpolated into SQL, so nothing else is allowed).
    """
    if not dates:
        raise ValueError("dates must not be empty")
    if offset < 0:
        raise ValueError(f"offset must not be negative, got {offset}")
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError(f"unsafe or malformed symbol: {symbol!r}")
    in_list = ", ".join(f"'{d.isoformat()}'" for d in sorted(set(dates)))
    return (
        f"SELECT {', '.join(_COLUMNS)} FROM option_chain"
        f" WHERE act_symbol = '{symbol}' AND date IN ({in_list})"
        f" ORDER BY date, expiration, strike, call_put"
        f" LIMIT {PAGE_SIZE} OFFSET {offset}"
    )


def parse_rows(rows: Sequence[Mapping[str, str | None]], *, ingested_at: datetime) -> pd.DataFrame:
    """Map DoltHub ``option_chain`` rows to a bronze-shaped frame.

    Every DoltHub value arrives as a string or null. ``date`` becomes ``trade_date``,
    ``act_symbol`` becomes ``underlying``, ``call_put`` (``Call``/``Put``) becomes ``right``
    (``C``/``P``), ``vol`` becomes ``iv``; ``occ_symbol`` is built from the contract terms;
    ``source`` is ``"dolthub"``; ``last``, ``volume``, ``open_interest`` and
    ``underlying_price`` are null. Rows repeating an ``(occ_symbol, trade_date)`` already
    seen are dropped, keeping the first. Rows with a crossed quote (bid above ask, both
    present) are dropped, and a WARNING is logged with the count per underlying and date.

    The frame is not validated; the caller runs ``BRONZE_FRAME.validate``.

    Args:
        rows: The ``rows`` array of one or more DoltHub responses.
        ingested_at: Timezone-aware UTC instant stamped on every row.

    Returns:
        A frame with BRONZE_SCHEMA's columns and dtypes; ``empty_frame()`` for no rows.

    Raises:
        ValueError: If ``ingested_at`` is naive, or a row lacks a key column or holds a value
            that does not parse (an unknown ``call_put``, a malformed date or number).
    """
    stamp = utc_instant(ingested_at)
    records: dict[tuple[str, date], dict[str, Any]] = {}
    for row in rows:
        record = _parse_row(row, stamp)
        records.setdefault((record["occ_symbol"], record["trade_date"]), record)
    kept, dropped = split_crossed_quotes(list(records.values()))
    for (underlying, trade_date), count in sorted(dropped.items()):
        logger.warning(
            "dolthub: dropped %d crossed quotes (bid > ask) for %s on %s",
            count,
            underlying,
            trade_date,
        )
    return frame_from_records(kept)


def month_chunks(dates: Sequence[date]) -> list[list[date]]:
    """Group dates by calendar month.

    Args:
        dates: Dates in any order, possibly repeated.

    Returns:
        One list per (year, month) present, in ascending month order; each list is sorted
        and free of duplicates. Empty input gives an empty list.
    """
    chunks: dict[tuple[int, int], list[date]] = {}
    for d in sorted(set(dates)):
        chunks.setdefault((d.year, d.month), []).append(d)
    return [chunks[month] for month in sorted(chunks)]


class DoltHubClient:
    """HTTP client for DoltHub's SQL read API, with retries.

    Args:
        http: Client to send requests with; tests pass one built on ``httpx.MockTransport``.
            A default client with a 60-second timeout is created when omitted.
        base_url: SQL endpoint of the database branch.
        page_pause_s: Seconds to wait between consecutive page requests in ``query_pages``,
            to stay polite to a free API. Zero disables the pause.
        retry_wait: tenacity wait strategy between attempts. Defaults to
            ``wait_random_exponential(multiplier=1, max=60)``; tests pass ``wait_none()``.
        max_attempts: Attempts per query, including the first.
    """

    page_pause_s: float

    def __init__(
        self,
        http: httpx.Client | None = None,
        *,
        base_url: str = DOLTHUB_BASE_URL,
        page_pause_s: float = 0.25,
        retry_wait: wait_base | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        """Store the transport and retry policy; no request is sent."""
        self._http = http if http is not None else httpx.Client(timeout=60.0)
        self._base_url = base_url
        self.page_pause_s = page_pause_s
        self._retry_wait = (
            retry_wait if retry_wait is not None else wait_random_exponential(multiplier=1, max=60)
        )
        self._max_attempts = max_attempts

    def query(self, sql: str) -> tuple[str, list[dict[str, str | None]]]:
        """Run one SQL query and return its status and rows.

        Sends ``GET base_url?q=<sql>``. Retries, with the configured wait, on
        ``httpx.TransportError`` (except ``LocalProtocolError``), HTTP 429 and 5xx responses,
        and on an ``Error`` status whose message contains ``deadline exceeded``, for at most
        ``max_attempts`` attempts. Transport errors are reported by class name only, and the
        body of a 401/403 response is not repeated, so error text cannot carry secrets.

        Args:
            sql: The SQL text.

        Returns:
            ``(query_execution_status, rows)``: status is ``"Success"`` or ``"RowLimit"``;
            rows are dicts of column name to string or None.

        Raises:
            DoltHubError: On an ``Error`` status that is not a timeout, on any other non-2xx
                HTTP status, on a response that is not the documented JSON shape, or when
                every attempt failed with a retryable error (the last one is chained as
                ``__cause__``).
        """
        retrying = Retrying(
            wait=self._retry_wait,
            stop=stop_after_attempt(self._max_attempts),
            retry=retry_if_exception_type(_RetryableError),
        )
        try:
            return retrying(self._query_once, sql)
        except RetryError as e:
            cause = e.last_attempt.exception()
            raise DoltHubError(
                f"DoltHub query failed after {self._max_attempts} attempts: {cause}"
            ) from cause

    def query_pages(self, page_sql: Callable[[int], str]) -> list[dict[str, str | None]]:
        """Run a paged query to the end and return every row.

        Calls ``page_sql(offset)`` for the SQL of each page, starting at offset 0 and
        advancing the offset by the rows actually received. Waits ``page_pause_s`` before
        every page after the first. Stops on an empty page, or on a short page whose status
        is ``Success``. A full page reported as ``Success`` (what DoltHub returns when the
        query carries its own ``LIMIT``) and any ``RowLimit`` page, even a short one truncated
        by the server, continue the loop.

        Args:
            page_sql: Builds the SQL of the page that starts at the given row offset.

        Returns:
            The rows of all pages, in order.

        Raises:
            DoltHubError: If a query fails (see ``query``).
        """
        rows: list[dict[str, str | None]] = []
        offset = 0
        while True:
            if offset and self.page_pause_s > 0:
                time.sleep(self.page_pause_s)
            status, page = self.query(page_sql(offset))
            rows.extend(page)
            if not page or (len(page) < PAGE_SIZE and status == "Success"):
                return rows
            offset += len(page)

    def _query_once(self, sql: str) -> tuple[str, list[dict[str, str | None]]]:
        """Send one request; raise ``_RetryableError`` for failures worth retrying."""
        try:
            response = self._http.get(self._base_url, params={"q": sql})
        except httpx.LocalProtocolError as e:
            # Raised before sending (malformed request); not transient, and its text is not
            # repeated because it can quote request headers.
            raise DoltHubError(f"transport error: {type(e).__name__}") from None
        except httpx.TransportError as e:
            raise _RetryableError(f"transport error: {type(e).__name__}") from None
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableError(f"HTTP {response.status_code}")
        if response.status_code in (401, 403):
            raise DoltHubError(f"HTTP {response.status_code}: access denied")
        if response.is_error:
            raise DoltHubError(f"HTTP {response.status_code}: {response.text[:200]}")
        try:
            body = response.json()
        except ValueError as e:
            raise DoltHubError("response is not JSON") from e
        if not isinstance(body, dict) or not isinstance(body.get("rows", []), list):
            raise DoltHubError(f"unexpected response shape: {str(body)[:200]}")
        status = body.get("query_execution_status")
        message = str(body.get("query_execution_message", ""))
        if status == "Error":
            if "deadline exceeded" in message:
                raise _RetryableError(message)
            raise DoltHubError(message)
        if status not in ("Success", "RowLimit"):
            raise DoltHubError(f"unexpected query_execution_status {status!r}")
        rows: list[dict[str, str | None]] = body.get("rows") or []
        return status, rows


def fetch_chain(
    symbol: str,
    start: date,
    end: date,
    *,
    client: DoltHubClient,
    ingested_at: datetime | None = None,
) -> pd.DataFrame:
    """Fetch and validate the option chain for one symbol over a date range.

    Queries only NYSE session days in ``[start, end]``, one month per query, paging each month
    as described in the module docstring, then parses and validates the union.
    Logs one INFO line per month with its row count.

    Args:
        symbol: Underlying ticker, for example ``"SPY"``.
        start: First trade date, inclusive.
        end: Last trade date, inclusive.
        client: DoltHub client to query through.
        ingested_at: UTC instant stamped on every row; the current time when omitted.

    Returns:
        A frame that passed ``BRONZE_FRAME.validate(frame, lazy=True)``, with
        ``source == "dolthub"``; ``empty_frame()`` when DoltHub holds no rows for the range.

    Raises:
        ValueError: If ``start`` is after ``end``.
        DoltHubError: If a query fails (see ``DoltHubClient.query``).
        pandera.errors.SchemaErrors: If the parsed rows break the bronze contract; validation
            is lazy, so every failed check is listed.
    """
    sessions = trading_days(start, end)
    stamp = ingested_at if ingested_at is not None else datetime.now(UTC)
    rows: list[dict[str, str | None]] = []
    for month in month_chunks(sessions):
        month_rows = client.query_pages(functools.partial(build_query, symbol, month))
        logger.info(
            "dolthub %s %s: %d rows over %d sessions",
            symbol,
            f"{month[0]:%Y-%m}",
            len(month_rows),
            len(month),
        )
        rows.extend(month_rows)
    frame = parse_rows(rows, ingested_at=stamp)
    return BRONZE_FRAME.validate(frame, lazy=True)
