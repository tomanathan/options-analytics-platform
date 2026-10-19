import re
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pyiceberg.catalog
import pytest
from tenacity import wait_none

from dags import backfill_chains, backfill_prices
from oap.ingest.dolthub import DOLTHUB_BASE_URL, DOLTHUB_STOCKS_URL, DoltHubClient
from oap.ingest.dolthub_stocks import stocks_client
from oap.ingest.iceberg_writer import (
    catalog_from_env,
    ensure_table,
    read_partition,
    table_identifier,
    write_partition,
)
from oap.ingest.tables import OPTION_CHAIN, UNDERLYING_PRICE
from scripts import refresh_bronze as refresh
from tests.bronze_factory import bronze_frame, dolthub_row
from tests.ingest.price_factory import ohlcv_row

# Mon 2024-01-29 to Fri 2024-02-02: five sessions over two months.
START = date(2024, 1, 29)
END = date(2024, 2, 2)
SESSIONS = ["2024-01-29", "2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02"]
ARGS = ["--start", "2024-01-29", "--end", "2024-02-02", "--workers", "2"]

QUOTED_DATE = re.compile(r"'(\d{4}-\d{2}-\d{2})'")
CHAIN_SYMBOL = re.compile(r"act_symbol = '([A-Z.\-0-9]+)'")
PRICE_SYMBOLS = re.compile(r"act_symbol IN \(([^)]*)\)")


class DoltHubMock:
    """A MockTransport handler that answers both DoltHub databases from the query text.

    A chain query returns two contracts per requested date for its symbol, a price query one
    bar per requested symbol and date. ``fail`` is a set of ``(database, symbol, month)``;
    a matching query gets HTTP 400, which the client does not retry.
    """

    def __init__(self, fail: set[tuple[str, str, str]] | None = None) -> None:
        self.fail = fail or set()
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        sql = request.url.params["q"]
        dates = QUOTED_DATE.findall(sql)
        chains = "/options/" in request.url.path
        if chains:
            symbols = [CHAIN_SYMBOL.search(sql).group(1)]  # type: ignore[union-attr]
        else:
            symbols = re.findall(r"'([A-Z.\-0-9]+)'", PRICE_SYMBOLS.search(sql).group(1))  # type: ignore[union-attr]
        database = "options" if chains else "stocks"
        if any((database, symbol, dates[0][:7]) in self.fail for symbol in symbols):
            return httpx.Response(400, text="bad request")
        if chains:
            rows = [
                dolthub_row(
                    trade_date=d,
                    symbol=symbols[0],
                    expiration="2024-03-15",
                    strike=strike,
                    call_put=right,
                )
                for d in dates
                for strike, right in (("470.00", "Call"), ("480.00", "Put"))
            ]
        else:
            rows = [ohlcv_row(trade_date=d, symbol=s) for d in dates for s in symbols]
        body = {"query_execution_status": "Success", "query_execution_message": "", "rows": rows}
        return httpx.Response(200, json=body)

    def paths(self) -> set[str]:
        return {request.url.path for request in self.requests}


def _clients(
    mock: DoltHubMock, created: list[DoltHubClient] | None = None
) -> tuple[Callable[[], DoltHubClient], Callable[[], DoltHubClient]]:
    def chain() -> DoltHubClient:
        client = DoltHubClient(
            httpx.Client(transport=httpx.MockTransport(mock)),
            base_url=DOLTHUB_BASE_URL,
            page_pause_s=0,
            retry_wait=wait_none(),
        )
        if created is not None:
            created.append(client)
        return client

    def prices() -> DoltHubClient:
        return stocks_client(
            httpx.Client(transport=httpx.MockTransport(mock)),
            page_pause_s=0,
            retry_wait=wait_none(),
        )

    return chain, prices


@pytest.fixture
def catalog(tmp_path: Path) -> pyiceberg.catalog.Catalog:
    return catalog_from_env(
        {
            "OAP_ICEBERG_CATALOG": "sql",
            "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/catalog.db",
            "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/warehouse",
        }
    )


def _run(
    catalog: pyiceberg.catalog.Catalog,
    mock: DoltHubMock,
    argv: list[str],
    created: list[DoltHubClient] | None = None,
) -> int:
    chain, prices = _clients(mock, created)
    return refresh.main(
        ["--symbols", "SPY,QQQ", *argv],
        catalog=catalog,
        chain_client=chain,
        price_client=prices,
        today=END,
    )


def _summary_line(capsys: pytest.CaptureFixture[str]) -> str:
    # Importing the DAG modules (for the plan comparison) makes Airflow route logging to stdout,
    # so the summary is the last line rather than the only one.
    return capsys.readouterr().out.strip().splitlines()[-1]


def _snapshots(catalog: pyiceberg.catalog.Catalog) -> dict[str, int]:
    return {
        spec.name: len(catalog.load_table(table_identifier(spec=spec)).snapshots())
        for spec in (OPTION_CHAIN, UNDERLYING_PRICE)
    }


def _underlyings(
    catalog: pyiceberg.catalog.Catalog, spec_name: str, day: str, source: str
) -> set[str]:
    spec = OPTION_CHAIN if spec_name == "option_chain" else UNDERLYING_PRICE
    table = catalog.load_table(table_identifier(spec=spec))
    frame = read_partition(table, trade_date=date.fromisoformat(day), source=source, spec=spec)
    return {str(u) for u in frame["underlying"].unique()}


# Defaults


def test_default_start_is_n_sessions_before_the_last_session() -> None:
    # Sessions before Mon 2026-10-19, newest first: Oct 16, 15, 14, 13, 12, 9, 8, 7, 6, 5.
    assert refresh.default_start(date(2026, 10, 19), 10) == date(2026, 10, 5)


def test_default_start_skips_holidays() -> None:
    # Fri Jan 2, Wed Dec 31, Tue Dec 30; Thursday 2026-01-01 is a holiday.
    assert refresh.default_start(date(2026, 1, 5), 3) == date(2025, 12, 30)


def test_default_start_counts_from_the_last_session_when_end_is_a_weekend() -> None:
    # Sunday 2026-10-18: the last session is Fri Oct 16, two sessions back is Wed Oct 14.
    assert refresh.default_start(date(2026, 10, 18), 2) == date(2026, 10, 14)


def test_default_start_rejects_a_lookback_below_one() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        refresh.default_start(date(2026, 10, 19), 0)


def test_resolve_window_defaults_end_to_today_and_start_to_the_lookback() -> None:
    assert refresh.resolve_window(None, None, lookback_sessions=10, today=date(2026, 10, 19)) == (
        date(2026, 10, 5),
        date(2026, 10, 19),
    )


def test_resolve_window_keeps_explicit_dates() -> None:
    assert refresh.resolve_window(START, END, lookback_sessions=10, today=date(2030, 1, 1)) == (
        START,
        END,
    )


def test_resolve_window_rejects_start_after_end() -> None:
    with pytest.raises(ValueError, match="after end"):
        refresh.resolve_window(END, START, lookback_sessions=10, today=END)


def test_read_watchlist_reads_the_seed_without_repeats() -> None:
    symbols = refresh.read_watchlist()

    assert "SPY" in symbols
    assert len(symbols) == len(set(symbols)) >= 2


def test_read_watchlist_cleans_a_file(tmp_path: Path) -> None:
    seed = tmp_path / "watchlist.csv"
    seed.write_text("symbol,sector\nspy,a\n  aapl ,b\n,c\nSPY,d\n")

    assert refresh.read_watchlist(seed) == ["SPY", "AAPL"]


# Planning


def test_plan_chain_jobs_is_one_job_per_month_and_symbol_ordered_by_month() -> None:
    jobs = refresh.plan_chain_jobs(START, END, ["SPY", "AAPL"])

    assert [(j.month, j.symbols, j.start, j.end) for j in jobs] == [
        ("2024-01", ("SPY",), date(2024, 1, 29), date(2024, 1, 31)),
        ("2024-01", ("AAPL",), date(2024, 1, 29), date(2024, 1, 31)),
        ("2024-02", ("SPY",), date(2024, 2, 1), date(2024, 2, 2)),
        ("2024-02", ("AAPL",), date(2024, 2, 1), date(2024, 2, 2)),
    ]
    assert {j.table for j in jobs} == {"chains"}


def test_plan_chain_jobs_has_no_job_for_a_window_without_a_session() -> None:
    # Sat 2024-01-13, Sun, and the Martin Luther King holiday on Mon.
    assert refresh.plan_chain_jobs(date(2024, 1, 13), date(2024, 1, 15), ["SPY"]) == []
    assert refresh.plan_price_jobs(date(2024, 1, 13), date(2024, 1, 15), ["SPY"]) == []


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2024, 1, 29), date(2024, 2, 2)),
        (date(2023, 11, 20), date(2024, 1, 5)),
        (date(2024, 3, 28), date(2024, 4, 2)),
    ],
)
def test_plan_chain_jobs_matches_the_backfill_dag(start: date, end: date) -> None:
    symbols = ["SPY", "AAPL", "TSLA"]

    ours = [
        (j.symbols[0], j.start.isoformat(), j.end.isoformat())
        for j in refresh.plan_chain_jobs(start, end, symbols)
    ]
    dag = [
        (j["symbol"], j["start"], j["end"]) for j in backfill_chains.plan_jobs(start, end, symbols)
    ]

    assert ours == dag


def test_plan_price_jobs_is_one_job_per_month_with_every_symbol() -> None:
    jobs = refresh.plan_price_jobs(START, END, ["SPY", "AAPL"])

    assert [(j.month, j.symbols, j.start, j.end) for j in jobs] == [
        ("2024-01", ("SPY", "AAPL"), date(2024, 1, 29), date(2024, 1, 31)),
        ("2024-02", ("SPY", "AAPL"), date(2024, 2, 1), date(2024, 2, 2)),
    ]
    assert {j.table for j in jobs} == {"prices"}


def test_plan_price_jobs_matches_the_backfill_dag() -> None:
    symbols = ["SPY", "AAPL"]

    ours = [
        (j.month, j.start.isoformat(), j.end.isoformat())
        for j in refresh.plan_price_jobs(date(2023, 11, 20), date(2024, 1, 5), symbols)
    ]
    dag = [
        (j["month"], j["start"], j["end"])
        for j in backfill_prices.plan_months(date(2023, 11, 20), date(2024, 1, 5), symbols)
    ]

    assert ours == dag


# Summary


def test_summarise_adds_up_fetches_and_writes() -> None:
    chain = refresh.Job("chains", "2024-01", START, END, ("SPY",))
    other = refresh.Job("chains", "2024-01", START, END, ("QQQ",))
    price = refresh.Job("prices", "2024-01", START, END, ("SPY", "QQQ"))
    fetches = [
        refresh.FetchResult(chain, 100),
        refresh.FetchResult(other, 0, "DoltHubError: HTTP 400"),
        refresh.FetchResult(price, 10),
    ]
    writes = [
        refresh.WriteResult("chains", "2024-01", 3, 1, 100),
        refresh.WriteResult("prices", "2024-01", 2, 0, 10),
    ]

    summary = refresh.summarise(fetches, writes)

    assert summary.jobs == {"chains": 2, "prices": 1}
    assert summary.failures == ("chains QQQ 2024-01: DoltHubError: HTTP 400",)
    assert (summary.rows_fetched, summary.slices_written, summary.slices_unchanged) == (110, 5, 1)
    assert summary.rows_written == 110
    assert summary.line == (
        "refresh summary: 3 jobs (2 chains, 1 prices), 1 failed; 110 rows fetched; "
        "wrote 5 slices (110 rows), 1 unchanged"
    )


def test_summarise_of_nothing_is_zero() -> None:
    summary = refresh.summarise([], [])

    assert summary.failures == ()
    assert summary.line.startswith("refresh summary: 0 jobs (), 0 failed; 0 rows fetched")


def test_job_label_names_a_symbol_or_a_count() -> None:
    assert refresh.Job("chains", "2024-01", START, END, ("SPY",)).label == "chains SPY 2024-01"
    assert (
        refresh.Job("prices", "2024-01", START, END, ("A", "B")).label == "prices 2 symbols 2024-01"
    )


# Argument errors


@pytest.mark.parametrize(
    "argv",
    [
        ["--symbols", "spy;drop"],
        ["--symbols", ","],
        ["--tables", "options"],
        ["--start", "2024-02-02", "--end", "2024-01-29"],
        ["--start", "not-a-date"],
        ["--workers", "0"],
        ["--lookback-sessions", "0"],
    ],
)
def test_bad_arguments_exit_with_two_before_the_catalog_is_touched(
    catalog: pyiceberg.catalog.Catalog, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        refresh.main(argv, catalog=catalog, today=END)

    assert exit_info.value.code == 2
    assert catalog.list_namespaces() == []


# A run against the mock


def test_a_run_writes_both_tables_slice_by_slice(
    catalog: pyiceberg.catalog.Catalog, capsys: pytest.CaptureFixture[str]
) -> None:
    mock = DoltHubMock()

    code = _run(catalog, mock, ARGS)

    assert code == 0
    for day in SESSIONS:
        assert _underlyings(catalog, "option_chain", day, "dolthub") == {"SPY", "QQQ"}
        assert _underlyings(catalog, "underlying_price", day, "dolthub_stocks") == {"SPY", "QQQ"}
    # 2 symbols x 5 days x 2 contracts, and 2 symbols x 5 days; 10 slices.
    assert _summary_line(capsys) == (
        "refresh summary: 6 jobs (4 chains, 2 prices), 0 failed; 30 rows fetched; "
        "wrote 10 slices (30 rows), 0 unchanged"
    )
    # One chain query per (symbol, month), one price query per month.
    assert len(mock.requests) == 6
    assert mock.paths() == {
        httpx.URL(DOLTHUB_BASE_URL).path,
        httpx.URL(DOLTHUB_STOCKS_URL).path,
    }


def test_default_symbols_are_the_watchlist(catalog: pyiceberg.catalog.Catalog) -> None:
    mock = DoltHubMock()
    chain, prices = _clients(mock)

    code = refresh.main(
        ["--start", "2024-01-31", "--end", "2024-01-31", "--tables", "prices"],
        catalog=catalog,
        price_client=prices,
        chain_client=chain,
        today=END,
    )

    assert code == 0
    assert _underlyings(catalog, "underlying_price", "2024-01-31", "dolthub_stocks") == set(
        refresh.read_watchlist()
    )


def test_tables_prices_touches_neither_the_chain_database_nor_its_table(
    catalog: pyiceberg.catalog.Catalog,
) -> None:
    mock = DoltHubMock()

    code = _run(catalog, mock, [*ARGS, "--tables", "prices"])

    assert code == 0
    assert mock.paths() == {httpx.URL(DOLTHUB_STOCKS_URL).path}
    assert catalog.list_tables("bronze") == [("bronze", "underlying_price")]


def test_a_run_over_unchanged_data_adds_no_snapshots(
    catalog: pyiceberg.catalog.Catalog, capsys: pytest.CaptureFixture[str]
) -> None:
    mock = DoltHubMock()
    assert _run(catalog, mock, ARGS) == 0
    before = _snapshots(catalog)
    capsys.readouterr()

    assert _run(catalog, mock, ARGS) == 0

    assert _snapshots(catalog) == before
    assert _summary_line(capsys) == (
        "refresh summary: 6 jobs (4 chains, 2 prices), 0 failed; 30 rows fetched; "
        "wrote 0 slices (0 rows), 10 unchanged"
    )


def test_a_symbol_the_run_did_not_fetch_keeps_its_rows(
    catalog: pyiceberg.catalog.Catalog,
) -> None:
    table = ensure_table(catalog, table_identifier(spec=OPTION_CHAIN), spec=OPTION_CHAIN)
    write_partition(
        table,
        bronze_frame(date(2024, 1, 30), underlyings=("ZZZ",), rows_per_underlying=4),
        trade_date=date(2024, 1, 30),
        source="dolthub",
    )

    assert _run(catalog, DoltHubMock(), ARGS) == 0

    assert _underlyings(catalog, "option_chain", "2024-01-30", "dolthub") == {"SPY", "QQQ", "ZZZ"}


def test_a_failed_fetch_exits_one_names_the_job_and_still_writes_the_rest(
    catalog: pyiceberg.catalog.Catalog, capsys: pytest.CaptureFixture[str]
) -> None:
    mock = DoltHubMock(fail={("options", "QQQ", "2024-02"), ("stocks", "SPY", "2024-01")})

    code = _run(catalog, mock, ARGS)

    out = capsys.readouterr()
    assert code == 1
    assert "2 failed" in out.out
    assert "failed: chains QQQ 2024-02: DoltHubError: HTTP 400: bad request" in out.err
    assert "failed: prices 2 symbols 2024-01: DoltHubError" in out.err
    # QQQ's January chains and everything else that arrived are in.
    assert _underlyings(catalog, "option_chain", "2024-01-30", "dolthub") == {"SPY", "QQQ"}
    assert _underlyings(catalog, "option_chain", "2024-02-01", "dolthub") == {"SPY"}
    assert _underlyings(catalog, "underlying_price", "2024-02-01", "dolthub_stocks") == {
        "SPY",
        "QQQ",
    }
    assert _underlyings(catalog, "underlying_price", "2024-01-30", "dolthub_stocks") == set()


def test_each_worker_thread_gets_its_own_client(catalog: pyiceberg.catalog.Catalog) -> None:
    created: list[DoltHubClient] = []

    code = _run(catalog, DoltHubMock(), [*ARGS, "--tables", "chains"], created)

    assert code == 0
    # Four chain jobs on two workers: each thread builds one client and reuses it.
    assert 1 <= len(created) <= 2
    assert len({id(client) for client in created}) == len(created)
