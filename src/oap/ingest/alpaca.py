"""Daily option chain snapshots from Alpaca's market data API (indicative feed).

Alpaca serves the current state of every listed contract for an underlying: latest quote,
latest trade, the day's bar, implied volatility and greeks. A snapshot taken after the close
is the day's end-of-day chain, so ``snapshot_chain`` stamps every row with the session date
passed in as ``as_of``. The indicative feed is free and delayed; it is labelled
``alpaca_indicative`` in bronze so it is never confused with a consolidated feed.

The network boundary is ``AlpacaClient`` (credentials from ``ALPACA_API_KEY`` and
``ALPACA_SECRET_KEY``); ``parse_snapshots`` is pure. Alpaca does not report open interest, so
``open_interest`` lands as null. Prices are dollars per share, implied volatility a decimal,
volume in contracts. Contract terms come from the OCC symbol, which Alpaca returns in the
compact form (no padding spaces), the same form bronze stores.
"""

import logging
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, Self

import httpx
import pandas as pd
from tenacity import RetryError, Retrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_base, wait_random_exponential

from oap.ingest.schema import (
    BRONZE_FRAME,
    empty_frame,
    frame_from_records,
    parse_occ_symbol,
    split_crossed_quotes,
    utc_instant,
)

logger = logging.getLogger(__name__)

ALPACA_DATA_URL = "https://data.alpaca.markets"
"""Base URL of Alpaca's market data API (options snapshots and stock trades)."""

MAX_ATTEMPTS = 6
"""Attempts per request, including the first, before ``AlpacaClient`` gives up."""


SOURCE = "alpaca_indicative"
"""Value of ``source`` on every row this module produces."""

KEY_ID_ENV = "ALPACA_API_KEY"
SECRET_KEY_ENV = "ALPACA_SECRET_KEY"  # pragma: allowlist secret (variable name, not a value)
SNAPSHOT_PAGE_LIMIT = 1000
_GREEKS = ("delta", "gamma", "theta", "vega", "rho")


class AlpacaError(Exception):
    """Alpaca credentials are missing, a request failed, or retries were exhausted."""


class _RetryableError(Exception):
    """A failure worth another attempt: transport error or HTTP 429/5xx."""


def _float(obj: Mapping[str, Any] | None, key: str) -> float | None:
    if obj is None or obj.get(key) is None:
        return None
    return float(obj[key])


def _parse_snapshot(
    symbol: str,
    snapshot: Any,
    underlying: str,
    as_of: date,
    underlying_price: float | None,
    ingested_at: datetime,
) -> dict[str, Any] | None:
    """Map one snapshot to a bronze record, or None if it has neither quote nor trade."""
    if not isinstance(snapshot, Mapping):
        raise ValueError(f"snapshot for {symbol!r} is not an object")
    quote = snapshot.get("latestQuote") or None
    trade = snapshot.get("latestTrade") or None
    if quote is None and trade is None:
        return None
    root, expiration, right, strike = parse_occ_symbol(symbol)
    if root != underlying:
        raise ValueError(f"snapshot {symbol!r} is not an option on {underlying!r}")
    greeks = snapshot.get("greeks") or None
    bar = snapshot.get("dailyBar") or None
    volume = bar.get("v") if bar is not None else None
    record: dict[str, Any] = {
        "trade_date": as_of,
        "underlying": underlying,
        "occ_symbol": symbol.replace(" ", ""),
        "expiration": expiration,
        "strike": strike,
        "right": right,
        "bid": _float(quote, "bp"),
        "ask": _float(quote, "ap"),
        "last": _float(trade, "p"),
        "volume": None if volume is None else int(volume),
        "open_interest": None,
        "iv": _float(snapshot, "impliedVolatility"),
        "underlying_price": underlying_price,
        "source": SOURCE,
        "ingested_at": ingested_at,
    }
    for greek in _GREEKS:
        record[greek] = _float(greeks, greek)
    return record


def parse_snapshots(
    payload: Mapping[str, Any],
    *,
    underlying: str,
    as_of: date,
    underlying_price: float | None,
    ingested_at: datetime,
) -> pd.DataFrame:
    """Map an Alpaca option snapshots payload to a bronze-shaped frame.

    One row per key of ``payload["snapshots"]``. ``bid``/``ask`` come from
    ``latestQuote.bp``/``latestQuote.ap``, ``last`` from ``latestTrade.p``, ``volume`` from
    ``dailyBar.v``, ``iv`` from ``impliedVolatility`` and the greeks from ``greeks``; any
    missing sub-object or field becomes null. ``expiration``, ``strike`` and ``right`` are
    parsed from the OCC symbol key, which is stored without spaces. ``source`` is
    ``"alpaca_indicative"``, ``open_interest`` is null and ``trade_date`` is ``as_of``.
    Snapshots with neither ``latestQuote`` nor ``latestTrade`` carry no price and are
    skipped. Rows with a crossed quote (bid above ask, both present) are dropped, and a
    WARNING is logged with the count.

    The frame is not validated; the caller runs ``BRONZE_FRAME.validate``.

    Args:
        payload: A snapshots response body, or several merged, with a ``snapshots`` mapping.
        underlying: Underlying ticker the snapshots were requested for.
        as_of: Session date the snapshot represents.
        underlying_price: Latest underlying trade price in dollars, or None if unknown.
        ingested_at: Timezone-aware UTC instant stamped on every row.

    Returns:
        A frame with BRONZE_SCHEMA's columns and dtypes; ``empty_frame()`` when no snapshot
        has a quote or trade.

    Raises:
        ValueError: If ``ingested_at`` is naive, ``payload`` has no ``snapshots`` mapping, or
            a key is not a well-formed OCC symbol for ``underlying``.
    """
    stamp = utc_instant(ingested_at)
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, Mapping):
        raise ValueError("payload has no 'snapshots' mapping")
    records: list[dict[str, Any]] = []
    for symbol, snapshot in snapshots.items():
        record = _parse_snapshot(symbol, snapshot, underlying, as_of, underlying_price, stamp)
        if record is not None:
            records.append(record)
    kept, dropped = split_crossed_quotes(records)
    for (name, trade_date), count in sorted(dropped.items()):
        logger.warning(
            "alpaca: dropped %d crossed quotes (bid > ask) for %s on %s", count, name, trade_date
        )
    return frame_from_records(kept)


class AlpacaClient:
    """HTTP client for Alpaca's market data API, with retries.

    Args:
        key_id: Alpaca API key id, sent as ``APCA-API-KEY-ID``.
        secret_key: Alpaca API secret, sent as ``APCA-API-SECRET-KEY``.
        http: Client to send requests with; tests pass one built on ``httpx.MockTransport``.
            A default client with a 30-second timeout is created when omitted.
        base_url: Market data base URL.
        retry_wait: tenacity wait strategy between attempts. Defaults to
            ``wait_random_exponential(multiplier=1, max=60)``; tests pass ``wait_none()``.
        max_attempts: Attempts per request, including the first.
    """

    def __init__(
        self,
        key_id: str,
        secret_key: str,
        http: httpx.Client | None = None,
        *,
        base_url: str = ALPACA_DATA_URL,
        retry_wait: wait_base | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        """Store credentials, transport and retry policy; no request is sent."""
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
        self._http = http if http is not None else httpx.Client(timeout=30.0)
        self._base_url = base_url.rstrip("/")
        self._retry_wait = (
            retry_wait if retry_wait is not None else wait_random_exponential(multiplier=1, max=60)
        )
        self._max_attempts = max_attempts

    @classmethod
    def from_env(cls) -> Self:
        """Build a client from ``ALPACA_API_KEY`` and ``ALPACA_SECRET_KEY``.

        Returns:
            A client with the default transport, base URL and retry policy.

        Raises:
            AlpacaError: If either variable is unset or empty.
        """
        values = {name: os.environ.get(name, "") for name in (KEY_ID_ENV, SECRET_KEY_ENV)}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise AlpacaError(f"missing Alpaca credentials: {', '.join(missing)} not set")
        return cls(values[KEY_ID_ENV], values[SECRET_KEY_ENV])

    def option_snapshots(self, underlying: str) -> dict[str, Any]:
        """Fetch every option snapshot for an underlying, following pagination.

        Sends ``GET /v1beta1/options/snapshots/{underlying}?feed=indicative&limit=1000`` and
        repeats with ``page_token`` while the response carries a ``next_page_token``.
        Retries on ``httpx.TransportError``, HTTP 429 and 5xx.

        Args:
            underlying: Underlying ticker, for example ``"SPY"``.

        Returns:
            ``{"snapshots": {...}}`` holding the snapshots of every page, keyed by OCC symbol.

        Raises:
            AlpacaError: On any other non-2xx status, a malformed body, or exhausted retries
                (the last error is chained as ``__cause__``).
        """
        merged: dict[str, Any] = {}
        params: dict[str, str | int] = {"feed": "indicative", "limit": SNAPSHOT_PAGE_LIMIT}
        while True:
            body = self._get(f"/v1beta1/options/snapshots/{underlying}", params)
            snapshots = body.get("snapshots") or {}
            if not isinstance(snapshots, dict):
                raise AlpacaError(f"unexpected snapshots payload for {underlying}")
            merged.update(snapshots)
            token = body.get("next_page_token")
            if not token:
                return {"snapshots": merged}
            params = {**params, "page_token": str(token)}

    def latest_underlying_prices(self, symbols: Sequence[str]) -> dict[str, float]:
        """Fetch the latest trade price of each underlying.

        Sends ``GET /v2/stocks/trades/latest?symbols=A,B&feed=iex``. Retries as
        ``option_snapshots`` does.

        Args:
            symbols: Underlying tickers.

        Returns:
            Ticker to latest trade price in dollars. Tickers Alpaca has no trade for are
            absent.

        Raises:
            AlpacaError: As for ``option_snapshots``.
        """
        body = self._get("/v2/stocks/trades/latest", {"symbols": ",".join(symbols), "feed": "iex"})
        trades = body.get("trades") or {}
        if not isinstance(trades, dict):
            raise AlpacaError("unexpected latest trades payload")
        prices: dict[str, float] = {}
        for symbol, trade in trades.items():
            if isinstance(trade, dict) and trade.get("p") is not None:
                prices[symbol] = float(trade["p"])
        return prices

    def _get(self, path: str, params: Mapping[str, str | int]) -> dict[str, Any]:
        """GET a JSON object with retries; raise ``AlpacaError`` on failure."""
        retrying = Retrying(
            wait=self._retry_wait,
            stop=stop_after_attempt(self._max_attempts),
            retry=retry_if_exception_type(_RetryableError),
        )
        try:
            return retrying(self._get_once, path, params)
        except RetryError as e:
            cause = e.last_attempt.exception()
            raise AlpacaError(
                f"Alpaca request {path} failed after {self._max_attempts} attempts: {cause}"
            ) from cause

    def _get_once(self, path: str, params: Mapping[str, str | int]) -> dict[str, Any]:
        """Send one request; raise ``_RetryableError`` for failures worth retrying."""
        try:
            response = self._http.get(
                self._base_url + path, params=dict(params), headers=self._headers
            )
        except httpx.TransportError as e:
            raise _RetryableError(f"transport error: {e!r}") from e
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableError(f"HTTP {response.status_code}")
        if response.is_error:
            raise AlpacaError(f"HTTP {response.status_code} for {path}: {response.text[:200]}")
        try:
            body = response.json()
        except ValueError as e:
            raise AlpacaError(f"response for {path} is not JSON") from e
        if not isinstance(body, dict):
            raise AlpacaError(f"unexpected response shape for {path}")
        return body


def snapshot_chain(
    symbols: Sequence[str],
    as_of: date,
    *,
    client: AlpacaClient,
    ingested_at: datetime | None = None,
) -> pd.DataFrame:
    """Snapshot, parse and validate the option chains of several underlyings.

    Fetches the underlying prices first (one request), then each symbol's snapshots, so the
    underlying price is never later than the option quotes it accompanies. Logs one INFO
    line per symbol with its row count.

    Args:
        symbols: Underlying tickers.
        as_of: Session date the snapshot represents, stamped as ``trade_date``.
        client: Alpaca client to request through.
        ingested_at: UTC instant stamped on every row; the current time when omitted.

    Returns:
        A frame that passed ``BRONZE_FRAME.validate(frame, lazy=True)``, with
        ``source == "alpaca_indicative"``; ``empty_frame()`` if no symbol had a priced
        contract.

    Raises:
        AlpacaError: If a request fails (see ``AlpacaClient``).
        pandera.errors.SchemaErrors: If the parsed rows break the bronze contract; validation
            is lazy, so every failed check is listed.
    """
    stamp = ingested_at if ingested_at is not None else datetime.now(UTC)
    prices = client.latest_underlying_prices(symbols)
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        payload = client.option_snapshots(symbol)
        frame = parse_snapshots(
            payload,
            underlying=symbol,
            as_of=as_of,
            underlying_price=prices.get(symbol),
            ingested_at=stamp,
        )
        logger.info(
            "alpaca %s %s: %d rows from %d snapshots",
            symbol,
            as_of,
            len(frame),
            len(payload["snapshots"]),
        )
        if len(frame):
            frames.append(frame)
    combined = pd.concat(frames, ignore_index=True) if frames else empty_frame()
    return BRONZE_FRAME.validate(combined, lazy=True)
