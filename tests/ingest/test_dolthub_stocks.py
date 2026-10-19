import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from tenacity import wait_none

from oap.calendar import trading_days
from oap.ingest.dolthub import DoltHubClient
from oap.ingest.dolthub_stocks import (
    SOURCE,
    build_price_query,
    fetch_prices,
    parse_price_rows,
    stocks_client,
)
from oap.ingest.price_schema import PRICE_FRAME, PRICE_SCHEMA
from tests.ingest.price_factory import INGESTED_AT, ohlcv_row

Handler = Callable[[httpx.Request], httpx.Response]

OFFSET = re.compile(r"OFFSET\s+(\d+)")
QUOTED_DATE = re.compile(r"'(\d{4}-\d{2}-\d{2})'")
IN_LIST = re.compile(r"date IN \(([^)]*)\)")
PAGE = 1000


def _ok(rows: list[dict[str, str | None]], status: str = "Success") -> httpx.Response:
    body = {"query_execution_status": status, "query_execution_message": "", "rows": rows}
    return httpx.Response(200, json=body)


class Recorder:
    """A MockTransport handler that records each request and replays queued responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses[min(len(self.requests), len(self.responses)) - 1]

    @property
    def queries(self) -> list[str]:
        return [request.url.params["q"] for request in self.requests]

    @property
    def offsets(self) -> list[int]:
        return [int(OFFSET.findall(q)[-1]) for q in self.queries]


def _client(handler: Handler) -> DoltHubClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return stocks_client(http, page_pause_s=0, retry_wait=wait_none())


# build_price_query


def test_build_price_query_has_the_exact_sql() -> None:
    sql = build_price_query(["SPY", "AAPL"], [date(2024, 1, 3), date(2024, 1, 2)], 0)

    assert sql == (
        "SELECT date, act_symbol, open, high, low, close, volume FROM ohlcv"
        " WHERE act_symbol IN ('AAPL', 'SPY') AND date IN ('2024-01-02', '2024-01-03')"
        " ORDER BY date, act_symbol LIMIT 1000 OFFSET 0"
    )


def test_build_price_query_sorts_and_deduplicates() -> None:
    sql = build_price_query(
        ["SPY", "QQQ", "SPY"], [date(2024, 1, 3), date(2024, 1, 2), date(2024, 1, 3)], 2000
    )

    assert "act_symbol IN ('QQQ', 'SPY')" in sql
    assert QUOTED_DATE.findall(sql) == ["2024-01-02", "2024-01-03"]
    assert sql.endswith("LIMIT 1000 OFFSET 2000")


@pytest.mark.parametrize(
    ("symbols", "dates", "offset"),
    [
        (["SPY'"], [date(2024, 1, 2)], 0),
        (["SPY' OR '1'='1"], [date(2024, 1, 2)], 0),
        (["spy"], [date(2024, 1, 2)], 0),
        (["SPY", ""], [date(2024, 1, 2)], 0),
        ([], [date(2024, 1, 2)], 0),
        (["SPY"], [], 0),
        (["SPY"], [date(2024, 1, 2)], -1),
    ],
)
def test_build_price_query_rejects_bad_input(
    symbols: list[str], dates: list[date], offset: int
) -> None:
    with pytest.raises(ValueError):
        build_price_query(symbols, dates, offset)


# parse_price_rows


def test_parse_price_rows_maps_a_known_row() -> None:
    frame = parse_price_rows([ohlcv_row()], ingested_at=INGESTED_AT)

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["trade_date"] == date(2024, 1, 5)
    assert row["underlying"] == "SPY"
    assert (row["open"], row["high"], row["low"], row["close"]) == (
        468.04,
        470.44,
        466.43,
        467.92,
    )
    assert row["volume"] == 86118913
    assert row["source"] == "dolthub_stocks" == SOURCE
    assert row["ingested_at"] == INGESTED_AT
    PRICE_FRAME.validate(frame, lazy=True)


def test_parse_price_rows_stores_ingested_at_in_utc() -> None:
    zone = timezone(timedelta(hours=-5))

    frame = parse_price_rows([ohlcv_row()], ingested_at=datetime(2024, 1, 3, 1, 0, tzinfo=zone))

    assert frame.iloc[0]["ingested_at"] == datetime(2024, 1, 3, 6, 0, tzinfo=UTC)


def test_parse_price_rows_drops_high_below_low_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    rows = [
        ohlcv_row(symbol="AAA", high="10.00", low="11.00", close="10.50"),
        ohlcv_row(symbol="AAA", trade_date="2024-01-08", high="10.00", low="11.00", close="10.5"),
        ohlcv_row(symbol="BBB"),
    ]

    with caplog.at_level(logging.WARNING):
        frame = parse_price_rows(rows, ingested_at=INGESTED_AT)

    assert list(frame["underlying"]) == ["BBB"]
    assert "dropped 2 rows with inconsistent OHLC for AAA" in caplog.text


@pytest.mark.parametrize(
    "row",
    [
        ohlcv_row(high="10.00", low="9.00", close="10.01"),
        ohlcv_row(high="10.00", low="9.00", close="8.99"),
        ohlcv_row(high="10.00", low=None, close="10.01"),
        ohlcv_row(high=None, low="9.00", close="8.99"),
    ],
)
def test_parse_price_rows_drops_a_close_outside_the_range(row: dict[str, str | None]) -> None:
    assert parse_price_rows([row], ingested_at=INGESTED_AT).empty


def test_parse_price_rows_drops_a_null_close_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    rows = [ohlcv_row(close=None), ohlcv_row(close=""), ohlcv_row(symbol="QQQ")]

    with caplog.at_level(logging.WARNING):
        frame = parse_price_rows(rows, ingested_at=INGESTED_AT)

    assert list(frame["underlying"]) == ["QQQ"]
    assert "dropped 2 rows without a close for SPY" in caplog.text


def test_parse_price_rows_keeps_an_open_outside_the_range_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # IWM 2021-05-05 as DoltHub holds it.
    row = ohlcv_row(
        symbol="IWM",
        trade_date="2021-05-05",
        open_="224.28",
        high="224.16",
        low="221.61",
        close="222.86",
        volume="29481000",
    )

    with caplog.at_level(logging.WARNING):
        frame = parse_price_rows([row], ingested_at=INGESTED_AT)

    assert len(frame) == 1
    assert frame.iloc[0]["open"] == 224.28
    assert "kept 1 rows with open outside [low, high] for IWM" in caplog.text
    PRICE_FRAME.validate(frame, lazy=True)


def test_parse_price_rows_keeps_the_first_of_a_repeated_key() -> None:
    rows = [ohlcv_row(close="467.00"), ohlcv_row(close="468.00"), ohlcv_row(symbol="QQQ")]

    frame = parse_price_rows(rows, ingested_at=INGESTED_AT)

    assert list(frame["underlying"]) == ["SPY", "QQQ"]
    assert frame.iloc[0]["close"] == 467.0


def test_parse_price_rows_reads_missing_open_high_low_volume_as_null() -> None:
    row = ohlcv_row(open_=None, high=None, low="", volume=None)

    frame = parse_price_rows([row], ingested_at=INGESTED_AT)

    assert len(frame) == 1
    assert frame.iloc[0][["open", "high", "low", "volume"]].isna().all()
    PRICE_FRAME.validate(frame, lazy=True)


def test_parse_price_rows_rejects_a_naive_ingested_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_price_rows([ohlcv_row()], ingested_at=datetime(2024, 1, 3, 6, 0))


@pytest.mark.parametrize(
    "row",
    [
        ohlcv_row(symbol=""),
        ohlcv_row(trade_date=""),
        ohlcv_row(trade_date="01/05/2024"),
        ohlcv_row(close="abc"),
        ohlcv_row(volume="1.5e3"),
    ],
)
def test_parse_price_rows_rejects_malformed_values(row: dict[str, str | None]) -> None:
    with pytest.raises(ValueError):
        parse_price_rows([row], ingested_at=INGESTED_AT)


def test_parse_price_rows_of_no_rows_is_the_empty_price_frame() -> None:
    frame = parse_price_rows([], ingested_at=INGESTED_AT)

    assert frame.empty
    assert list(frame.columns) == PRICE_SCHEMA.names
    PRICE_FRAME.validate(frame, lazy=True)


_cents = st.integers(min_value=1, max_value=1_000_000).map(lambda c: f"{c / 100:.2f}")
_rows = st.fixed_dictionaries(
    {
        "date": st.sampled_from(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "act_symbol": st.sampled_from(["SPY", "QQQ", "IWM"]),
        "open": st.none() | _cents,
        "high": st.none() | _cents,
        "low": st.none() | _cents,
        "close": st.none() | _cents,
        "volume": st.none() | st.integers(min_value=0, max_value=10**10).map(str),
    }
)


@given(rows=st.lists(_rows, max_size=40))
def test_parse_price_rows_output_is_a_valid_price_frame(rows: list[dict[str, str | None]]) -> None:
    frame = parse_price_rows(rows, ingested_at=INGESTED_AT)

    PRICE_FRAME.validate(frame, lazy=True)
    assert len(frame) <= len(rows)
    assert not frame.duplicated(["underlying", "trade_date"]).any()
    assert set(frame["source"]) <= {"dolthub_stocks"}
    for close, low, high in zip(frame["close"], frame["low"], frame["high"], strict=True):
        assert pd.isna(low) or close >= low
        assert pd.isna(high) or close <= high


# fetch_prices


def test_fetch_prices_sends_one_query_per_month_with_all_symbols() -> None:
    recorder = Recorder([_ok([])])

    fetch_prices(
        ["spy", "QQQ", "SPY"], date(2024, 1, 2), date(2024, 2, 29), client=_client(recorder)
    )

    assert len(recorder.queries) == 2
    sessions = trading_days(date(2024, 1, 2), date(2024, 2, 29))
    for query, month in zip(recorder.queries, (1, 2), strict=True):
        assert "act_symbol IN ('QQQ', 'SPY')" in query
        match = IN_LIST.search(query)
        assert match is not None
        listed = [date.fromisoformat(d) for d in QUOTED_DATE.findall(match.group(1))]
        assert listed == [d for d in sessions if d.month == month]
    assert date(2024, 1, 15) not in sessions  # a market holiday: never queried
    assert "'2024-01-15'" not in recorder.queries[0]


def test_fetch_prices_returns_a_validated_frame() -> None:
    rows = [ohlcv_row(), ohlcv_row(symbol="QQQ", close="400.00", high="401.00", low="399.00")]
    recorder = Recorder([_ok(rows)])

    frame = fetch_prices(
        ["SPY", "QQQ"], date(2024, 1, 5), date(2024, 1, 5), client=_client(recorder)
    )

    assert sorted(frame["underlying"]) == ["QQQ", "SPY"]
    PRICE_FRAME.validate(frame, lazy=True)


def test_fetch_prices_pages_until_a_short_page() -> None:
    full = [ohlcv_row(symbol=f"T{i:04d}") for i in range(PAGE)]
    short = [ohlcv_row(symbol=f"U{i:04d}") for i in range(3)]
    recorder = Recorder([_ok(full), _ok(short)])

    frame = fetch_prices(["SPY"], date(2024, 1, 5), date(2024, 1, 5), client=_client(recorder))

    assert recorder.offsets == [0, PAGE]
    assert len(frame) == PAGE + 3


def test_fetch_prices_logs_one_line_per_month(caplog: pytest.LogCaptureFixture) -> None:
    recorder = Recorder([_ok([ohlcv_row()])])

    with caplog.at_level(logging.INFO, logger="oap.ingest.dolthub_stocks"):
        fetch_prices(["SPY"], date(2024, 1, 5), date(2024, 1, 5), client=_client(recorder))

    assert "dolthub_stocks 2024-01: 1 rows for 1 symbols over 1 sessions" in caplog.text


def test_fetch_prices_empty_is_empty_frame() -> None:
    recorder = Recorder([_ok([])])

    frame = fetch_prices(["SPY"], date(2024, 1, 2), date(2024, 1, 31), client=_client(recorder))

    assert frame.empty
    assert list(frame.columns) == PRICE_SCHEMA.names


def test_fetch_prices_with_no_session_in_range_sends_nothing() -> None:
    recorder = Recorder([_ok([])])

    frame = fetch_prices(["SPY"], date(2024, 1, 6), date(2024, 1, 7), client=_client(recorder))

    assert frame.empty
    assert recorder.queries == []


@pytest.mark.parametrize("symbols", [[], [" "], ["SPY'"]])
def test_fetch_prices_rejects_bad_symbols_before_any_request(symbols: list[str]) -> None:
    recorder = Recorder([_ok([])])

    with pytest.raises(ValueError):
        fetch_prices(symbols, date(2024, 1, 2), date(2024, 1, 31), client=_client(recorder))
    assert recorder.queries == []


def test_fetch_prices_rejects_a_reversed_range() -> None:
    with pytest.raises(ValueError):
        fetch_prices(
            ["SPY"], date(2024, 2, 1), date(2024, 1, 1), client=_client(Recorder([_ok([])]))
        )


def test_stocks_client_targets_the_stocks_db() -> None:
    recorder = Recorder([_ok([])])

    stocks_client(httpx.Client(transport=httpx.MockTransport(recorder))).query("SELECT 1")

    assert recorder.requests[0].url.path.endswith("/stocks/master")
    assert "post-no-preference/stocks" in recorder.requests[0].url.path
