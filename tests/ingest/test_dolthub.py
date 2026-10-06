import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from tenacity import wait_none

from oap.ingest.dolthub import (
    PAGE_SIZE,
    DoltHubClient,
    DoltHubError,
    build_query,
    fetch_chain,
    month_chunks,
    parse_rows,
)
from oap.ingest.schema import BRONZE_FRAME, BRONZE_SCHEMA
from tests.bronze_factory import INGESTED_AT, dolthub_row, dolthub_rows

Handler = Callable[[httpx.Request], httpx.Response]

OFFSET = re.compile(r"OFFSET\s+(\d+)")
QUOTED_DATE = re.compile(r"'(\d{4}-\d{2}-\d{2})'")


def _body(status: str, rows: list[dict[str, str | None]], message: str = "") -> dict[str, object]:
    return {
        "query_execution_status": status,
        "query_execution_message": message,
        "rows": rows,
        "schema": [],
    }


def _ok(rows: list[dict[str, str | None]], status: str = "Success") -> httpx.Response:
    return httpx.Response(200, json=_body(status, rows))


def _client(handler: Handler) -> DoltHubClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return DoltHubClient(http, page_pause_s=0, retry_wait=wait_none())


class Recorder:
    """A MockTransport handler that records each SQL query and replays queued responses."""

    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses
        self.queries: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.queries.append(request.url.params["q"])
        response = self.responses[min(len(self.queries), len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def offsets(self) -> list[int]:
        return [int(OFFSET.findall(q)[-1]) for q in self.queries]


# build_query


def test_build_query_filters_symbol_and_dates_with_an_in_list() -> None:
    sql = build_query("SPY", [date(2024, 1, 2), date(2024, 1, 3)], 0)

    assert "option_chain" in sql
    assert "'SPY'" in sql
    assert re.search(r"date\s+IN\s*\(\s*'2024-01-02'\s*,\s*'2024-01-03'\s*\)", sql)
    assert " BETWEEN " not in sql.upper()
    assert ">=" not in sql


def test_build_query_orders_by_primary_key_and_pages() -> None:
    sql = build_query("SPY", [date(2024, 1, 2)], 2000)

    assert "ORDER BY date, expiration, strike, call_put" in sql
    assert sql.rstrip().endswith("LIMIT 1000 OFFSET 2000")


def test_build_query_first_page_has_offset_zero() -> None:
    assert build_query("QQQ", [date(2024, 1, 2)], 0).rstrip().endswith("LIMIT 1000 OFFSET 0")


def test_build_query_rejects_empty_dates() -> None:
    with pytest.raises(ValueError):
        build_query("SPY", [], 0)


def test_build_query_rejects_negative_offset() -> None:
    with pytest.raises(ValueError):
        build_query("SPY", [date(2024, 1, 2)], -1000)


@pytest.mark.parametrize("symbol", ["", "spy", "SPY'", "SPY' OR '1'='1", "TOOLONG"])
def test_build_query_rejects_unsafe_symbols(symbol: str) -> None:
    with pytest.raises(ValueError):
        build_query(symbol, [date(2024, 1, 2)], 0)


# month_chunks


def test_month_chunks_splits_across_a_month_boundary() -> None:
    dates = [date(2024, 1, 30), date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 2)]

    assert month_chunks(dates) == [
        [date(2024, 1, 30), date(2024, 1, 31)],
        [date(2024, 2, 1), date(2024, 2, 2)],
    ]


def test_month_chunks_separates_same_month_of_different_years() -> None:
    dates = [date(2025, 1, 2), date(2024, 1, 2)]

    assert month_chunks(dates) == [[date(2024, 1, 2)], [date(2025, 1, 2)]]


def test_month_chunks_of_nothing_is_empty() -> None:
    assert month_chunks([]) == []


@given(st.lists(st.dates(min_value=date(2020, 1, 1), max_value=date(2026, 12, 31))))
def test_month_chunks_partition_sorted_unique_dates_by_month(dates: list[date]) -> None:
    chunks = month_chunks(dates)

    assert [d for chunk in chunks for d in chunk] == sorted(set(dates))
    for chunk in chunks:
        assert chunk
        assert len({(d.year, d.month) for d in chunk}) == 1
    months = [(chunk[0].year, chunk[0].month) for chunk in chunks]
    assert months == sorted(set(months))


# parse_rows


def test_parse_rows_maps_a_known_row() -> None:
    frame = parse_rows([dolthub_row()], ingested_at=INGESTED_AT)

    assert list(frame.columns) == BRONZE_SCHEMA.names
    row = frame.iloc[0]
    assert row["trade_date"] == date(2024, 1, 2)
    assert row["underlying"] == "SPY"
    assert row["occ_symbol"] == "SPY240119C00470000"
    assert row["expiration"] == date(2024, 1, 19)
    assert row["strike"] == Decimal("470.00")
    assert row["right"] == "C"
    assert row["bid"] == pytest.approx(1.10)
    assert row["ask"] == pytest.approx(1.20)
    assert row["iv"] == pytest.approx(0.15)
    assert row["delta"] == pytest.approx(0.5)
    assert row["theta"] == pytest.approx(-0.2)
    assert row["source"] == "dolthub"
    assert row["ingested_at"] == INGESTED_AT
    for column in ("last", "volume", "open_interest", "underlying_price"):
        assert pd.isna(row[column]), column


def test_parse_rows_maps_put_to_p() -> None:
    frame = parse_rows([dolthub_row(call_put="Put", strike="465.50")], ingested_at=INGESTED_AT)

    assert frame.iloc[0]["right"] == "P"
    assert frame.iloc[0]["occ_symbol"] == "SPY240119P00465500"


def test_parse_rows_keeps_null_quotes_and_greeks_as_null() -> None:
    row = dolthub_row(bid=None, ask=None, vol=None, delta=None)

    frame = parse_rows([row], ingested_at=INGESTED_AT)

    for column in ("bid", "ask", "iv", "delta"):
        assert pd.isna(frame.iloc[0][column]), column


def test_parse_rows_drops_repeated_keys_keeping_the_first() -> None:
    first = dolthub_row(bid="1.00")
    repeat = dolthub_row(bid="9.00")

    frame = parse_rows([first, repeat, dolthub_row(call_put="Put")], ingested_at=INGESTED_AT)

    assert len(frame) == 2
    assert frame.loc[frame["right"] == "C", "bid"].tolist() == [pytest.approx(1.0)]


def test_parse_rows_of_nothing_is_an_empty_bronze_frame() -> None:
    frame = parse_rows([], ingested_at=INGESTED_AT)

    assert len(frame) == 0
    assert list(frame.columns) == BRONZE_SCHEMA.names
    BRONZE_FRAME.validate(frame)


def test_parse_rows_rejects_unknown_call_put() -> None:
    with pytest.raises(ValueError):
        parse_rows([dolthub_row(call_put="Straddle")], ingested_at=INGESTED_AT)


def test_parse_rows_rejects_naive_ingested_at() -> None:
    with pytest.raises(ValueError):
        parse_rows([dolthub_row()], ingested_at=datetime(2024, 1, 2, 22, 0))


def _price(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


@st.composite
def raw_rows(draw: st.DrawFn) -> list[dict[str, str | None]]:
    """DoltHub-shaped rows with valid contract terms, optional nulls and repeated keys."""
    symbol = draw(st.sampled_from(["SPY", "QQQ", "AAPL", "BRK"]))
    count = draw(st.integers(min_value=0, max_value=30))
    rows: list[dict[str, str | None]] = []
    for _ in range(count):
        trade_date = draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2026, 12, 31)))
        expiration = trade_date + timedelta(days=draw(st.integers(0, 900)))
        strike_cents = draw(st.integers(min_value=50, max_value=500_000))
        bid_cents = draw(st.none() | st.integers(min_value=0, max_value=50_000))
        spread_cents = draw(st.integers(min_value=0, max_value=500))
        ask: str | None
        if bid_cents is None:
            ask = draw(st.none() | st.integers(0, 50_000).map(_price))
        else:
            ask = draw(st.none() | st.just(_price(bid_cents + spread_cents)))
        vol = draw(st.none() | st.integers(1, 30_000).map(lambda v: f"{v / 10_000:.4f}"))
        rows.append(
            dolthub_row(
                trade_date=trade_date.isoformat(),
                symbol=symbol,
                expiration=expiration.isoformat(),
                strike=_price(strike_cents),
                call_put=draw(st.sampled_from(["Call", "Put"])),
                bid=None if bid_cents is None else _price(bid_cents),
                ask=ask,
                vol=vol,
            )
        )
    if rows:
        repeats = draw(st.lists(st.sampled_from(rows), max_size=5))
        rows.extend(dict(r) for r in repeats)
    return rows


@given(raw_rows())
def test_parse_rows_output_satisfies_the_bronze_contract(
    rows: list[dict[str, str | None]],
) -> None:
    frame = parse_rows(rows, ingested_at=INGESTED_AT)

    assert (frame["expiration"] >= frame["trade_date"]).all()
    both = frame["bid"].notna() & frame["ask"].notna()
    assert (frame.loc[both, "bid"] <= frame.loc[both, "ask"]).all()
    assert not frame.duplicated(subset=["occ_symbol", "trade_date"]).any()
    assert (frame["source"] == "dolthub").all()
    distinct_keys = {
        (r["date"], r["expiration"], Decimal(str(r["strike"])), r["call_put"]) for r in rows
    }
    assert len(frame) == len(distinct_keys)
    BRONZE_FRAME.validate(frame)


# DoltHubClient.query


def test_query_returns_status_and_rows() -> None:
    recorder = Recorder([_ok([dolthub_row()], status="RowLimit")])

    status, rows = _client(recorder).query("SELECT 1")

    assert status == "RowLimit"
    assert rows == [dolthub_row()]


def test_query_sends_the_sql_as_the_q_parameter() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok([])

    _client(handler).query("SELECT * FROM option_chain LIMIT 1")

    assert seen[0].method == "GET"
    assert seen[0].url.params["q"] == "SELECT * FROM option_chain LIMIT 1"
    assert str(seen[0].url).startswith(
        "https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master"
    )


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_query_retries_retryable_http_status_then_succeeds(status_code: int) -> None:
    recorder = Recorder([httpx.Response(status_code), _ok([dolthub_row()])])

    status, rows = _client(recorder).query("SELECT 1")

    assert (status, len(rows)) == ("Success", 1)
    assert len(recorder.queries) == 2


def test_query_retries_transport_errors_then_succeeds() -> None:
    recorder = Recorder([httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), _ok([])])

    assert _client(recorder).query("SELECT 1") == ("Success", [])
    assert len(recorder.queries) == 3


def test_query_retries_deadline_exceeded_then_succeeds() -> None:
    timeout = httpx.Response(200, json=_body("Error", [], "query error: context deadline exceeded"))
    recorder = Recorder([timeout, _ok([dolthub_row()])])

    status, rows = _client(recorder).query("SELECT 1")

    assert (status, len(rows)) == ("Success", 1)
    assert len(recorder.queries) == 2


def test_query_raises_on_a_non_retryable_error_status() -> None:
    error = httpx.Response(200, json=_body("Error", [], "table not found: option_chains"))
    recorder = Recorder([error, _ok([])])

    with pytest.raises(DoltHubError, match="table not found"):
        _client(recorder).query("SELECT 1")
    assert len(recorder.queries) == 1


def test_query_raises_on_a_client_error_without_retrying() -> None:
    recorder = Recorder([httpx.Response(404), _ok([])])

    with pytest.raises(DoltHubError):
        _client(recorder).query("SELECT 1")
    assert len(recorder.queries) == 1


def test_query_raises_on_a_body_that_is_not_the_documented_shape() -> None:
    recorder = Recorder([httpx.Response(200, content=json.dumps(["unexpected"]).encode())])

    with pytest.raises(DoltHubError):
        _client(recorder).query("SELECT 1")


def test_query_gives_up_after_six_attempts() -> None:
    recorder = Recorder([httpx.Response(503)])

    with pytest.raises(DoltHubError) as excinfo:
        _client(recorder).query("SELECT 1")

    assert len(recorder.queries) == 6
    assert excinfo.value.__cause__ is not None


# fetch_chain


def test_fetch_chain_pages_until_a_short_page() -> None:
    recorder = Recorder(
        [
            _ok(dolthub_rows(PAGE_SIZE, start=0), status="RowLimit"),
            _ok(dolthub_rows(PAGE_SIZE, start=PAGE_SIZE), status="RowLimit"),
            _ok(dolthub_rows(500, start=2 * PAGE_SIZE)),
        ]
    )

    frame = fetch_chain("SPY", date(2024, 1, 2), date(2024, 1, 2), client=_client(recorder))

    assert recorder.offsets == [0, 1000, 2000]
    assert len(frame) == 2500


def test_fetch_chain_keeps_paging_after_a_full_page_reported_as_success() -> None:
    # Verified against DoltHub: with an explicit LIMIT 1000 a full page reports "Success".
    recorder = Recorder(
        [_ok(dolthub_rows(PAGE_SIZE, start=0)), _ok(dolthub_rows(10, start=PAGE_SIZE))]
    )

    frame = fetch_chain("SPY", date(2024, 1, 2), date(2024, 1, 2), client=_client(recorder))

    assert recorder.offsets == [0, 1000]
    assert len(frame) == 1010


def test_fetch_chain_queries_only_trading_days() -> None:
    recorder = Recorder([_ok([])])

    fetch_chain("SPY", date(2024, 6, 29), date(2024, 7, 8), client=_client(recorder))

    queried = {date.fromisoformat(d) for q in recorder.queries for d in QUOTED_DATE.findall(q)}
    assert queried == {
        date(2024, 7, 1),
        date(2024, 7, 2),
        date(2024, 7, 3),
        date(2024, 7, 5),
        date(2024, 7, 8),
    }


def test_fetch_chain_sends_one_query_per_month() -> None:
    recorder = Recorder([_ok([])])

    fetch_chain("SPY", date(2024, 1, 30), date(2024, 2, 2), client=_client(recorder))

    assert len(recorder.queries) == 2
    first, second = ({d[:7] for d in QUOTED_DATE.findall(q)} for q in recorder.queries)
    assert first == {"2024-01"}
    assert second == {"2024-02"}


def test_fetch_chain_returns_an_empty_frame_when_nothing_comes_back() -> None:
    recorder = Recorder([_ok([])])

    frame = fetch_chain("SPY", date(2024, 1, 2), date(2024, 1, 5), client=_client(recorder))

    assert len(frame) == 0
    assert list(frame.columns) == BRONZE_SCHEMA.names
    for field in BRONZE_SCHEMA:
        assert frame[field.name].dtype == pd.ArrowDtype(field.type), field.name


def test_fetch_chain_returns_a_validated_frame_stamped_with_ingested_at() -> None:
    at = datetime(2024, 1, 3, 1, 2, 3, tzinfo=UTC)
    recorder = Recorder([_ok(dolthub_rows(20))])

    frame = fetch_chain(
        "SPY", date(2024, 1, 2), date(2024, 1, 2), client=_client(recorder), ingested_at=at
    )

    BRONZE_FRAME.validate(frame)
    assert (frame["source"] == "dolthub").all()
    assert (frame["ingested_at"] == at).all()
    assert len(frame) == 20


def test_fetch_chain_rejects_an_inverted_range() -> None:
    recorder = Recorder([_ok([])])

    with pytest.raises(ValueError):
        fetch_chain("SPY", date(2024, 1, 5), date(2024, 1, 2), client=_client(recorder))
    assert recorder.queries == []


def test_build_query_accepts_dotted_and_hyphenated_symbols() -> None:
    assert "act_symbol = 'BRK.B'" in build_query("BRK.B", [date(2024, 1, 2)], 0)
    assert "act_symbol = 'BF-B'" in build_query("BF-B", [date(2024, 1, 2)], 0)


def test_parse_rows_drops_crossed_quotes_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    rows = [
        dolthub_row(strike="470.00", bid="2.00", ask="1.00"),
        dolthub_row(strike="471.00", bid="1.50", ask="1.50"),
        dolthub_row(strike="472.00", bid="1.00", ask="1.10"),
        dolthub_row(strike="473.00", bid="3.00", ask=None),
    ]

    with caplog.at_level(logging.WARNING, logger="oap.ingest.dolthub"):
        frame = parse_rows(rows, ingested_at=INGESTED_AT)

    assert sorted(frame["strike"]) == [Decimal("471"), Decimal("472"), Decimal("473")]
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and r.name == "oap.ingest.dolthub"
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "dropped 1 crossed" in message
    assert "SPY" in message
    assert "2024-01-02" in message


def test_fetch_chain_logs_one_info_line_per_month(caplog: pytest.LogCaptureFixture) -> None:
    recorder = Recorder([_ok(dolthub_rows(3)), _ok([])])

    with caplog.at_level(logging.INFO, logger="oap.ingest.dolthub"):
        fetch_chain("SPY", date(2024, 1, 31), date(2024, 2, 1), client=_client(recorder))

    lines = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO and r.name == "oap.ingest.dolthub"
    ]
    assert len(lines) == 2
    assert "SPY" in lines[0] and "2024-01" in lines[0] and "3 rows" in lines[0]
    assert "SPY" in lines[1] and "2024-02" in lines[1] and "0 rows" in lines[1]


def test_fetch_chain_continues_after_a_short_row_limit_page() -> None:
    # A server-truncated page reports RowLimit even when it is shorter than PAGE_SIZE.
    recorder = Recorder(
        [
            _ok(dolthub_rows(600, start=0), status="RowLimit"),
            _ok(dolthub_rows(100, start=600)),
        ]
    )

    frame = fetch_chain("SPY", date(2024, 1, 2), date(2024, 1, 2), client=_client(recorder))

    assert recorder.offsets == [0, 600]
    assert len(frame) == 700


def test_fetch_chain_stops_on_an_empty_row_limit_page() -> None:
    recorder = Recorder([_ok(dolthub_rows(5), status="RowLimit"), _ok([], status="RowLimit")])

    frame = fetch_chain("SPY", date(2024, 1, 2), date(2024, 1, 2), client=_client(recorder))

    assert recorder.offsets == [0, 5]
    assert len(frame) == 5


def test_query_does_not_retry_or_echo_a_local_protocol_error() -> None:
    recorder = Recorder([httpx.LocalProtocolError("Illegal header value b'SECRET'")])

    with pytest.raises(DoltHubError) as excinfo:
        _client(recorder).query("SELECT 1")

    assert len(recorder.queries) == 1
    assert "SECRET" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_query_reports_transport_errors_by_class_name_only() -> None:
    recorder = Recorder([httpx.ConnectError("SECRET in a message")])

    with pytest.raises(DoltHubError) as excinfo:
        _client(recorder).query("SELECT 1")

    assert "ConnectError" in str(excinfo.value)
    assert "SECRET" not in str(excinfo.value)
    assert "SECRET" not in str(excinfo.value.__cause__)


@pytest.mark.parametrize("status", [401, 403])
def test_query_does_not_repeat_an_auth_failure_body(status: int) -> None:
    recorder = Recorder([httpx.Response(status, text="token SECRET rejected")])

    with pytest.raises(DoltHubError) as excinfo:
        _client(recorder).query("SELECT 1")

    assert "SECRET" not in str(excinfo.value)
