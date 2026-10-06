import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
from tenacity import wait_none

from oap.ingest.alpaca import (
    AlpacaClient,
    AlpacaError,
    newest_quote_time,
    parse_snapshots,
    snapshot_chain,
)
from oap.ingest.schema import BRONZE_FRAME, BRONZE_SCHEMA

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AS_OF = date(2026, 10, 5)
INGESTED_AT = datetime(2026, 10, 5, 20, 30, tzinfo=UTC)
SPY_PRICE = 668.42
SNAPSHOTS_PATH = "/v1beta1/options/snapshots/"
TRADES_PATH = "/v2/stocks/trades/latest"

Handler = Callable[[httpx.Request], httpx.Response]


def _load(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open() as f:
        loaded: dict[str, Any] = json.load(f)
    return loaded


@pytest.fixture
def page1() -> dict[str, Any]:
    return _load("alpaca_snapshots_spy_page1.json")


@pytest.fixture
def page2() -> dict[str, Any]:
    return _load("alpaca_snapshots_spy_page2.json")


@pytest.fixture
def merged(page1: dict[str, Any], page2: dict[str, Any]) -> dict[str, Any]:
    return {"snapshots": {**page1["snapshots"], **page2["snapshots"]}}


def _parse(payload: dict[str, Any], underlying_price: float | None = SPY_PRICE) -> pd.DataFrame:
    return parse_snapshots(
        payload,
        underlying="SPY",
        as_of=AS_OF,
        underlying_price=underlying_price,
        ingested_at=INGESTED_AT,
    )


def _row(frame: pd.DataFrame, symbol: str) -> "pd.Series[Any]":
    matches = frame[frame["occ_symbol"] == symbol]
    assert len(matches) == 1, symbol
    return matches.iloc[0]


class Router:
    """MockTransport handler serving the fixtures by path and recording every request."""

    def __init__(self, failures: list[httpx.Response | Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        path = request.url.path
        if path == TRADES_PATH:
            return httpx.Response(200, json=_load("alpaca_latest_trades.json"))
        if path == SNAPSHOTS_PATH + "SPY":
            if request.url.params.get("page_token") == "page-2":
                return httpx.Response(200, json=_load("alpaca_snapshots_spy_page2.json"))
            return httpx.Response(200, json=_load("alpaca_snapshots_spy_page1.json"))
        if path.startswith(SNAPSHOTS_PATH):
            return httpx.Response(200, json={"snapshots": {}, "next_page_token": None})
        return httpx.Response(404)


def _client(handler: Handler) -> AlpacaClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return AlpacaClient("test-key-id", "test-secret", http, retry_wait=wait_none())


# parse_snapshots


def test_parse_snapshots_one_row_per_priced_snapshot(merged: dict[str, Any]) -> None:
    frame = _parse(merged)

    assert list(frame.columns) == BRONZE_SCHEMA.names
    assert set(frame["occ_symbol"]) == {
        "SPY261016C00600000",
        "SPY261016P00600000",
        "SPY261120P00550500",
        "SPY261218C00700000",
    }


def test_parse_snapshots_skips_a_snapshot_without_quote_or_trade(merged: dict[str, Any]) -> None:
    frame = _parse(merged)

    assert "SPY261218P00500000" not in set(frame["occ_symbol"])


def test_parse_snapshots_maps_quote_trade_bar_and_greeks(merged: dict[str, Any]) -> None:
    row = _row(_parse(merged), "SPY261016P00600000")

    assert row["bid"] == pytest.approx(0.27)
    assert row["ask"] == pytest.approx(0.29)
    assert row["last"] == pytest.approx(0.28)
    assert row["volume"] == 5120
    assert row["iv"] == pytest.approx(0.2410)
    assert row["delta"] == pytest.approx(-0.0391)
    assert row["gamma"] == pytest.approx(0.0012)
    assert row["theta"] == pytest.approx(-0.0611)
    assert row["vega"] == pytest.approx(0.0902)
    assert row["rho"] == pytest.approx(-0.0071)
    assert row["underlying_price"] == pytest.approx(SPY_PRICE)


def test_parse_snapshots_stamps_source_dates_and_null_open_interest(
    merged: dict[str, Any],
) -> None:
    frame = _parse(merged)

    assert (frame["source"] == "alpaca_indicative").all()
    assert (frame["trade_date"] == AS_OF).all()
    assert (frame["underlying"] == "SPY").all()
    assert (frame["ingested_at"] == INGESTED_AT).all()
    assert frame["open_interest"].isna().all()


def test_parse_snapshots_parses_contract_terms_from_the_symbol(merged: dict[str, Any]) -> None:
    frame = _parse(merged)

    call = _row(frame, "SPY261016C00600000")
    assert (call["expiration"], call["strike"], call["right"]) == (
        date(2026, 10, 16),
        Decimal("600"),
        "C",
    )
    put = _row(frame, "SPY261120P00550500")
    assert (put["expiration"], put["strike"], put["right"]) == (
        date(2026, 11, 20),
        Decimal("550.5"),
        "P",
    )


def test_parse_snapshots_quote_only_contract_has_null_trade_fields(
    merged: dict[str, Any],
) -> None:
    row = _row(_parse(merged), "SPY261120P00550500")

    assert row["bid"] == pytest.approx(1.12)
    assert row["ask"] == pytest.approx(1.18)
    for column in ("last", "volume", "iv", "delta", "gamma", "theta", "vega", "rho"):
        assert pd.isna(row[column]), column


def test_parse_snapshots_trade_only_contract_has_null_bid_and_ask(merged: dict[str, Any]) -> None:
    row = _row(_parse(merged), "SPY261218C00700000")

    assert pd.isna(row["bid"])
    assert pd.isna(row["ask"])
    assert row["last"] == pytest.approx(3.05)
    assert row["volume"] == 1


def test_parse_snapshots_without_underlying_price_leaves_it_null(merged: dict[str, Any]) -> None:
    frame = _parse(merged, underlying_price=None)

    assert frame["underlying_price"].isna().all()


def test_parse_snapshots_output_validates(merged: dict[str, Any]) -> None:
    BRONZE_FRAME.validate(_parse(merged))


def test_parse_snapshots_of_an_empty_payload_is_an_empty_bronze_frame() -> None:
    frame = _parse({"snapshots": {}})

    assert len(frame) == 0
    assert list(frame.columns) == BRONZE_SCHEMA.names
    BRONZE_FRAME.validate(frame)


def test_parse_snapshots_rejects_a_payload_without_snapshots() -> None:
    with pytest.raises(ValueError):
        _parse({"quotes": {}})


def test_parse_snapshots_rejects_a_symbol_for_another_underlying(page1: dict[str, Any]) -> None:
    payload = {"snapshots": {"QQQ261016C00600000": page1["snapshots"]["SPY261016C00600000"]}}

    with pytest.raises(ValueError):
        _parse(payload)


# AlpacaClient


def test_option_snapshots_follows_next_page_token_and_merges() -> None:
    router = Router()

    payload = _client(router).option_snapshots("SPY")

    assert len(router.requests) == 2
    assert "page_token" not in router.requests[0].url.params
    assert router.requests[1].url.params["page_token"] == "page-2"
    assert len(payload["snapshots"]) == 5


def test_option_snapshots_requests_the_indicative_feed() -> None:
    router = Router()

    _client(router).option_snapshots("SPY")

    first = router.requests[0]
    assert first.method == "GET"
    assert first.url.host == "data.alpaca.markets"
    assert first.url.path == "/v1beta1/options/snapshots/SPY"
    assert first.url.params["feed"] == "indicative"
    assert first.url.params["limit"] == "1000"


def test_client_sends_auth_headers() -> None:
    router = Router()

    _client(router).option_snapshots("SPY")

    for request in router.requests:
        assert request.headers["APCA-API-KEY-ID"] == "test-key-id"
        assert request.headers["APCA-API-SECRET-KEY"] == "test-secret"


def test_latest_underlying_prices() -> None:
    router = Router()

    prices = _client(router).latest_underlying_prices(["SPY", "QQQ"])

    assert prices == {"SPY": pytest.approx(668.42), "QQQ": pytest.approx(601.17)}
    request = router.requests[0]
    assert request.url.path == TRADES_PATH
    assert request.url.params["symbols"] == "SPY,QQQ"
    assert request.url.params["feed"] == "iex"


@pytest.mark.parametrize(
    "failure",
    [httpx.Response(429), httpx.Response(503), httpx.ConnectError("refused")],
    ids=["429", "503", "transport"],
)
def test_client_retries_then_succeeds(failure: httpx.Response | Exception) -> None:
    router = Router(failures=[failure])

    prices = _client(router).latest_underlying_prices(["SPY"])

    assert prices["SPY"] == pytest.approx(668.42)
    assert len(router.requests) == 2


def test_client_raises_on_unauthorized_without_retrying() -> None:
    router = Router(failures=[httpx.Response(401, json={"message": "unauthorized"})])

    with pytest.raises(AlpacaError):
        _client(router).latest_underlying_prices(["SPY"])
    assert len(router.requests) == 1


def test_client_gives_up_after_six_attempts() -> None:
    router = Router(failures=[httpx.Response(503)] * 10)

    with pytest.raises(AlpacaError) as excinfo:
        _client(router).option_snapshots("SPY")

    assert len(router.requests) == 6
    assert excinfo.value.__cause__ is not None


def test_from_env_builds_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "env-key-id")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "env-secret")

    assert isinstance(AlpacaClient.from_env(), AlpacaClient)


@pytest.mark.parametrize("missing", ["ALPACA_API_KEY", "ALPACA_SECRET_KEY"])
def test_from_env_raises_without_keys(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "env-key-id")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "env-secret")
    monkeypatch.delenv(missing)

    with pytest.raises(AlpacaError, match=missing):
        AlpacaClient.from_env()


def test_from_env_treats_an_empty_key_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "env-secret")

    with pytest.raises(AlpacaError):
        AlpacaClient.from_env()


# snapshot_chain


def test_snapshot_chain_returns_a_validated_frame_with_the_underlying_price() -> None:
    router = Router()

    frame = snapshot_chain(["SPY"], AS_OF, client=_client(router), ingested_at=INGESTED_AT)

    BRONZE_FRAME.validate(frame)
    assert len(frame) == 4
    assert (frame["underlying_price"] == SPY_PRICE).all()
    assert (frame["trade_date"] == AS_OF).all()
    assert (frame["source"] == "alpaca_indicative").all()


def test_snapshot_chain_fetches_prices_before_snapshots() -> None:
    router = Router()

    snapshot_chain(["SPY"], AS_OF, client=_client(router), ingested_at=INGESTED_AT)

    paths = [r.url.path for r in router.requests]
    assert paths[0] == TRADES_PATH
    assert paths.count(TRADES_PATH) == 1


def test_snapshot_chain_tolerates_a_symbol_with_no_contracts_or_price() -> None:
    router = Router()

    frame = snapshot_chain(["SPY", "IWM"], AS_OF, client=_client(router), ingested_at=INGESTED_AT)

    assert set(frame["underlying"]) == {"SPY"}
    assert len(frame) == 4


def test_parse_snapshots_drops_crossed_quotes_and_warns(
    merged: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    crossed = dict(merged["snapshots"]["SPY261016P00600000"])
    crossed["latestQuote"] = {"t": "2026-10-05T19:59:59Z", "bp": 0.40, "bs": 1, "ap": 0.30, "as": 1}
    locked = dict(merged["snapshots"]["SPY261016C00600000"])
    locked["latestQuote"] = {"t": "2026-10-05T19:59:59Z", "bp": 68.9, "bs": 1, "ap": 68.9, "as": 1}
    payload = {
        "snapshots": {
            **merged["snapshots"],
            "SPY261016P00600000": crossed,
            "SPY261016C00600000": locked,
        }
    }

    with caplog.at_level(logging.WARNING, logger="oap.ingest.alpaca"):
        frame = _parse(payload)

    assert "SPY261016P00600000" not in set(frame["occ_symbol"])
    assert "SPY261016C00600000" in set(frame["occ_symbol"])
    assert len(frame) == 3
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "oap.ingest.alpaca"
    ]
    assert len(warnings) == 1
    assert "dropped 1 crossed" in warnings[0]
    assert "SPY" in warnings[0]


def test_snapshot_chain_logs_one_info_line_per_symbol(caplog: pytest.LogCaptureFixture) -> None:
    router = Router()

    with caplog.at_level(logging.INFO, logger="oap.ingest.alpaca"):
        snapshot_chain(["SPY", "IWM"], AS_OF, client=_client(router), ingested_at=INGESTED_AT)

    lines = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO and r.name == "oap.ingest.alpaca"
    ]
    assert len(lines) == 2
    assert "SPY" in lines[0] and "4 rows" in lines[0]
    assert "IWM" in lines[1] and "0 rows" in lines[1]


# secrets never reach error text


# The error names the variable (ALPACA_SECRET_KEY), so the echo check uses a distinct value.
LEAKY = "T0PS3CRETVALUE"


@pytest.mark.parametrize(
    "secret",
    [f"{LEAKY}\n", f"{LEAKY}\r\n", f"T0PS\t{LEAKY}", f"{LEAKY}\x00"],
    ids=["lf", "crlf", "tab", "nul"],
)
def test_from_env_rejects_a_key_with_control_characters_without_echoing_it(secret: str) -> None:
    env = {"ALPACA_API_KEY": "key-id", "ALPACA_SECRET_KEY": secret}  # pragma: allowlist secret

    with pytest.raises(AlpacaError) as excinfo:
        AlpacaClient.from_env(env)

    assert LEAKY not in str(excinfo.value)
    assert "ALPACA_SECRET_KEY" in str(excinfo.value)


def test_from_env_strips_surrounding_spaces() -> None:
    env = {"ALPACA_API_KEY": "  key-id ", "ALPACA_SECRET_KEY": " value  "}

    assert isinstance(AlpacaClient.from_env(env), AlpacaClient)


def test_the_constructor_rejects_a_key_with_a_newline() -> None:
    with pytest.raises(AlpacaError) as excinfo:
        AlpacaClient("key-id", f"{LEAKY}\n", httpx.Client(transport=httpx.MockTransport(Router())))

    assert LEAKY not in str(excinfo.value)


def test_a_local_protocol_error_is_not_retried_and_not_echoed() -> None:
    router = Router(failures=[httpx.LocalProtocolError("Illegal header value b'SECRET'")] * 6)

    with pytest.raises(AlpacaError) as excinfo:
        _client(router).latest_underlying_prices(["SPY"])

    assert len(router.requests) == 1
    assert "SECRET" not in str(excinfo.value)
    assert "LocalProtocolError" in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__


def test_a_retried_transport_error_reports_only_its_class_name() -> None:
    router = Router(failures=[httpx.ConnectError("SECRET in a message")] * 6)

    with pytest.raises(AlpacaError) as excinfo:
        _client(router).latest_underlying_prices(["SPY"])

    assert len(router.requests) == 6
    chain: BaseException | None = excinfo.value
    while chain is not None:
        assert "SECRET" not in str(chain)
        chain = chain.__cause__ or (None if chain.__suppress_context__ else chain.__context__)
    assert "ConnectError" in str(excinfo.value)


@pytest.mark.parametrize("status", [401, 403])
def test_an_auth_failure_does_not_repeat_the_response_body(status: int) -> None:
    router = Router(failures=[httpx.Response(status, text="denied for key SECRET")])

    with pytest.raises(AlpacaError) as excinfo:
        _client(router).latest_underlying_prices(["SPY"])

    assert "SECRET" not in str(excinfo.value)
    assert str(status) in str(excinfo.value)


# quotes must belong to the session


def test_newest_quote_time_takes_the_latest_quote_or_trade(merged: dict[str, Any]) -> None:
    # The latest of the fixtures' quote and trade times (SPY261016P00600000's quote).
    assert newest_quote_time(merged) == datetime(2026, 10, 5, 19, 59, 59, 733000, tzinfo=UTC)


def test_newest_quote_time_ignores_the_daily_bar_and_handles_nanoseconds() -> None:
    payload = {
        "snapshots": {
            "SPY261016C00600000": {
                "latestQuote": {"t": "2026-10-05T19:59:59.123456789Z", "bp": 1.0, "ap": 1.1},
                "latestTrade": {"t": "2026-10-05T18:00:00Z", "p": 1.05},
                "dailyBar": {"t": "2026-10-06T04:00:00Z", "v": 1},
            }
        }
    }

    assert newest_quote_time(payload) == datetime(2026, 10, 5, 19, 59, 59, 123456, tzinfo=UTC)


def test_newest_quote_time_of_a_payload_without_quotes_is_none() -> None:
    assert newest_quote_time({"snapshots": {}}) is None
    assert newest_quote_time({"snapshots": {"X": {"greeks": {"delta": 0.1}}}}) is None


def test_snapshot_chain_accepts_quotes_from_the_session() -> None:
    frame = snapshot_chain(["SPY"], AS_OF, client=_client(Router()), ingested_at=INGESTED_AT)

    assert len(frame) == 4


def test_snapshot_chain_rejects_quotes_from_another_session() -> None:
    next_session = date(2026, 10, 6)

    with pytest.raises(AlpacaError) as excinfo:
        snapshot_chain(["SPY"], next_session, client=_client(Router()), ingested_at=INGESTED_AT)

    message = str(excinfo.value)
    assert "2026-10-05" in message
    assert "2026-10-06" in message


def test_snapshot_chain_compares_dates_in_new_york_time() -> None:
    # 2026-10-06T01:30Z is still 2026-10-05 in New York (UTC-4).
    late = {"t": "2026-10-06T01:30:00Z", "bp": 1.0, "bs": 1, "ap": 1.1, "as": 1}
    payload = {"snapshots": {"SPY261016C00600000": {"latestQuote": late}}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TRADES_PATH:
            return httpx.Response(200, json=_load("alpaca_latest_trades.json"))
        return httpx.Response(200, json={**payload, "next_page_token": None})

    frame = snapshot_chain(["SPY"], AS_OF, client=_client(handler), ingested_at=INGESTED_AT)

    assert len(frame) == 1


def test_snapshot_chain_can_skip_the_session_check() -> None:
    frame = snapshot_chain(
        ["SPY"],
        date(2026, 10, 6),
        client=_client(Router()),
        ingested_at=INGESTED_AT,
        require_session_match=False,
    )

    assert (frame["trade_date"] == date(2026, 10, 6)).all()
