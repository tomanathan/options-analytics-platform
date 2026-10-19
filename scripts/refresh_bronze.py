"""Refresh the bronze tables from DoltHub for a window of sessions, without Airflow.

This is the nightly cloud job's ingest step (``.github/workflows/nightly.yml``, ADR 0012). It
does what ``backfill_chains`` and ``backfill_prices`` do, in one process:

* Chains: one fetch job per (symbol, month) with a session in the window, exactly the plan of
  ``dags.backfill_chains.plan_jobs``. The jobs run concurrently (``--workers`` threads, one
  ``DoltHubClient`` per thread), and the rows of each month are then merged into the daily
  ``(trade_date, "dolthub")`` slices of ``bronze.option_chain``, one month at a time.
* Prices: one fetch job per month for all symbols, merged into the
  ``(trade_date, "dolthub_stocks")`` slices of ``bronze.underlying_price``.

Writes go through ``oap.ingest.merge.merge_into_slices`` only (ADR 0003): a fetched underlying
replaces its own rows of a day, absence is not deletion, and a slice whose content did not
change is not written, so a second run over the same window adds no snapshots. A failed fetch
(after the client's own retries) does not stop the run: everything that did arrive is written,
the failures are printed, and the exit code is 1. Run it again; the merge makes that safe.

The window defaults to the last ``--lookback-sessions`` NYSE sessions up to today. DoltHub
publishes session D at about 05:30 UTC on D+1, so the newest bar is always a day behind and a
window that ends today asks for a session that does not exist yet; that costs one empty query.

The catalog comes from the environment (``oap.ingest.iceberg_writer.catalog_from_env``).
Nothing in ``dags`` is imported, so the script runs in the plain ``uv`` environment.

Usage: ``refresh_bronze.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--symbols SPY,DIA]
[--workers 4] [--tables chains,prices] [--lookback-sessions 10]``.
Exit codes: 0 when every fetch succeeded, 1 when any failed, 2 on bad arguments.
"""

import argparse
import csv
import logging
import sys
import threading
from collections import defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import pandas as pd
from pyiceberg.catalog import Catalog
from pyiceberg.table import Table

from oap.calendar import trading_days
from oap.ingest.dolthub import SYMBOL_PATTERN, DoltHubClient, fetch_chain, month_chunks
from oap.ingest.dolthub_stocks import SOURCE as PRICE_SOURCE
from oap.ingest.dolthub_stocks import fetch_prices, stocks_client
from oap.ingest.iceberg_writer import catalog_from_env, ensure_table, table_identifier
from oap.ingest.merge import merge_into_slices
from oap.ingest.tables import OPTION_CHAIN, UNDERLYING_PRICE, TableSpec

logger = logging.getLogger("refresh_bronze")

CHAINS: Final = "chains"
PRICES: Final = "prices"
TABLES: Final[tuple[str, ...]] = (CHAINS, PRICES)
"""Names accepted by ``--tables``, in the order they are refreshed."""

CHAIN_SOURCE: Final = "dolthub"
"""``source`` of the chain slices; the same value as ``oap.ingest.dolthub.SOURCE``."""

DEFAULT_LOOKBACK_SESSIONS: Final = 10
DEFAULT_WORKERS: Final = 4
WATCHLIST_PATH: Final = Path(__file__).resolve().parents[1] / "dbt" / "seeds" / "watchlist.csv"
"""The dbt watchlist seed, read here with the csv module so that no DAG module is imported."""

_ERROR_WIDTH: Final = 300
"""Characters of an exception message kept in a failure report."""


@dataclass(frozen=True)
class Job:
    """One fetch job: a set of symbols over the sessions of one calendar month.

    Attributes:
        table: ``"chains"`` or ``"prices"``.
        month: ``YYYY-MM`` of the sessions.
        start: First session of the month inside the window.
        end: Last session of the month inside the window.
        symbols: One ticker for a chain job, every ticker for a price job.
    """

    table: str
    month: str
    start: date
    end: date
    symbols: tuple[str, ...]

    @property
    def label(self) -> str:
        """Short text naming the job in logs and failure reports."""
        who = self.symbols[0] if len(self.symbols) == 1 else f"{len(self.symbols)} symbols"
        return f"{self.table} {who} {self.month}"


@dataclass(frozen=True)
class FetchResult:
    """What one fetch job produced.

    Attributes:
        job: The job.
        rows: Rows fetched and validated; 0 when the fetch failed or DoltHub had none.
        error: ``"ExceptionClass: message"`` when the fetch failed, otherwise None.
    """

    job: Job
    rows: int
    error: str | None = None


@dataclass(frozen=True)
class WriteResult:
    """What merging one month of one table wrote.

    Attributes:
        table: ``"chains"`` or ``"prices"``.
        month: ``YYYY-MM``.
        days: Slices written.
        unchanged: Slices skipped because their content did not change.
        rows: Rows written.
    """

    table: str
    month: str
    days: int
    unchanged: int
    rows: int


@dataclass(frozen=True)
class Summary:
    """Totals of a run.

    Attributes:
        jobs: Fetch jobs per table name.
        failures: ``"<job label>: <error>"`` for every failed fetch, in job order.
        rows_fetched: Rows fetched over all jobs.
        slices_written: Slices written.
        slices_unchanged: Slices skipped as unchanged.
        rows_written: Rows written.
    """

    jobs: dict[str, int]
    failures: tuple[str, ...]
    rows_fetched: int
    slices_written: int
    slices_unchanged: int
    rows_written: int

    @property
    def line(self) -> str:
        """The one-line summary the workflow copies into its step summary."""
        total = sum(self.jobs.values())
        by_table = ", ".join(f"{count} {name}" for name, count in self.jobs.items())
        return (
            f"refresh summary: {total} jobs ({by_table}), {len(self.failures)} failed; "
            f"{self.rows_fetched:,} rows fetched; wrote {self.slices_written:,} slices "
            f"({self.rows_written:,} rows), {self.slices_unchanged:,} unchanged"
        )


def read_watchlist(path: Path = WATCHLIST_PATH) -> list[str]:
    """Return the tickers of the watchlist seed, in file order.

    Args:
        path: CSV with a ``symbol`` column.

    Returns:
        Upper-cased tickers without blanks or repeats.
    """
    with path.open(newline="") as handle:
        return normalize_symbols([row["symbol"] for row in csv.DictReader(handle)])


def normalize_symbols(symbols: Sequence[str]) -> list[str]:
    """Upper-case and trim tickers, dropping blanks and repeats but keeping first-seen order.

    Args:
        symbols: Tickers as typed or read from the seed.

    Returns:
        The cleaned tickers.
    """
    cleaned = (symbol.strip().upper() for symbol in symbols)
    return list(dict.fromkeys(symbol for symbol in cleaned if symbol))


def default_start(end: date, lookback_sessions: int) -> date:
    """Return the session ``lookback_sessions`` sessions before the last one on or before ``end``.

    The window ``[default_start(end, n), end]`` therefore holds ``n + 1`` sessions when ``end``
    is a session day or follows one, which covers the newest session DoltHub has published
    plus ``n`` before it.

    Args:
        end: Last calendar date of the window.
        lookback_sessions: How many sessions to step back; at least 1.

    Returns:
        The start date, a session day.

    Raises:
        ValueError: If ``lookback_sessions`` is below 1.
    """
    if lookback_sessions < 1:
        raise ValueError(f"lookback_sessions must be at least 1, got {lookback_sessions}")
    span = lookback_sessions * 2 + 7
    while True:
        sessions = trading_days(end - timedelta(days=span), end)
        if len(sessions) > lookback_sessions:
            return sessions[-(lookback_sessions + 1)]
        span *= 2


def resolve_window(
    start: date | None, end: date | None, *, lookback_sessions: int, today: date
) -> tuple[date, date]:
    """Fill in the defaults of ``--start`` and ``--end``.

    Args:
        start: ``--start``, or None for ``default_start``.
        end: ``--end``, or None for ``today``.
        lookback_sessions: Sessions to step back when ``start`` is None.
        today: The date to use as the default end.

    Returns:
        ``(start, end)``.

    Raises:
        ValueError: If the window is empty (``start`` after ``end``) or ``lookback_sessions``
            is below 1.
    """
    last = end if end is not None else today
    first = start if start is not None else default_start(last, lookback_sessions)
    if first > last:
        raise ValueError(f"start {first} is after end {last}")
    return first, last


def plan_chain_jobs(start: date, end: date, symbols: Sequence[str]) -> list[Job]:
    """List one chain fetch job per (symbol, month) with at least one session in range.

    The plan is that of ``dags.backfill_chains.plan_jobs``: months from ``month_chunks`` over
    ``trading_days``, ordered by month and then by symbol.

    Args:
        start: First calendar date, inclusive.
        end: Last calendar date, inclusive.
        symbols: Cleaned tickers.

    Returns:
        The jobs. ``start`` and ``end`` of a job are the first and last session of its month
        inside the range.

    Raises:
        ValueError: If ``start`` is after ``end``.
    """
    return [
        Job(CHAINS, f"{chunk[0]:%Y-%m}", chunk[0], chunk[-1], (symbol,))
        for chunk in month_chunks(trading_days(start, end))
        for symbol in symbols
    ]


def plan_price_jobs(start: date, end: date, symbols: Sequence[str]) -> list[Job]:
    """List one price fetch job per month with at least one session in range.

    A job carries every symbol, because DoltHub answers a month for the whole watchlist in one
    query (``dags.backfill_prices.plan_months``).

    Args:
        start: First calendar date, inclusive.
        end: Last calendar date, inclusive.
        symbols: Cleaned tickers.

    Returns:
        The jobs in month order.

    Raises:
        ValueError: If ``start`` is after ``end``.
    """
    return [
        Job(PRICES, f"{chunk[0]:%Y-%m}", chunk[0], chunk[-1], tuple(symbols))
        for chunk in month_chunks(trading_days(start, end))
    ]


def summarise(fetches: Sequence[FetchResult], writes: Sequence[WriteResult]) -> Summary:
    """Add up the results of a run. Pure.

    Args:
        fetches: One result per fetch job.
        writes: One result per month written.

    Returns:
        The totals; ``jobs`` counts the jobs of each table that appears in ``fetches``.
    """
    jobs: dict[str, int] = {}
    for fetch in fetches:
        jobs[fetch.job.table] = jobs.get(fetch.job.table, 0) + 1
    return Summary(
        jobs=jobs,
        failures=tuple(f"{f.job.label}: {f.error}" for f in fetches if f.error is not None),
        rows_fetched=sum(f.rows for f in fetches),
        slices_written=sum(w.days for w in writes),
        slices_unchanged=sum(w.unchanged for w in writes),
        rows_written=sum(w.rows for w in writes),
    )


class _ThreadClients:
    """Hands every thread its own client: ``httpx.Client`` and the retry state are not shared."""

    def __init__(self, factory: Callable[[], DoltHubClient]) -> None:
        self._factory = factory
        self._local = threading.local()

    def get(self) -> DoltHubClient:
        client: DoltHubClient | None = getattr(self._local, "client", None)
        if client is None:
            client = self._factory()
            self._local.client = client
        return client


def _fetch(job: Job, clients: _ThreadClients) -> pd.DataFrame:
    """Fetch and validate one job's rows through the calling thread's client."""
    client = clients.get()
    if job.table == CHAINS:
        return fetch_chain(job.symbols[0], job.start, job.end, client=client)
    return fetch_prices(job.symbols, job.start, job.end, client=client)


def _describe(error: BaseException) -> str:
    """Return ``"ClassName: message"`` with the message cut to a readable length."""
    text = " ".join(str(error).split())
    if len(text) > _ERROR_WIDTH:
        text = text[: _ERROR_WIDTH - 3] + "..."
    return f"{type(error).__name__}: {text}"


def refresh_table(
    table: Table,
    spec: TableSpec,
    source: str,
    jobs: Sequence[Job],
    clients: _ThreadClients,
    *,
    workers: int,
) -> tuple[list[FetchResult], list[WriteResult]]:
    """Fetch a table's jobs concurrently and merge them into its slices month by month.

    Every job is submitted to the thread pool at once. The main thread then takes the months
    in order, waits for that month's jobs, and merges what arrived with one
    ``merge_into_slices`` call, so writes are serial. A month with a failed fetch is still
    written with the symbols that arrived: ``merge_into_slices`` replaces only the underlyings
    it is given, so a missing symbol keeps the rows it already has.

    Args:
        table: The bronze table to write.
        spec: The table's spec.
        source: Feed of the slices to merge into.
        jobs: Output of ``plan_chain_jobs`` or ``plan_price_jobs``.
        clients: Per-thread client holder for this table's DoltHub database.
        workers: Fetch threads.

    Returns:
        The fetch results in job order and the write results in month order.
    """
    fetches: list[FetchResult] = []
    writes: list[WriteResult] = []
    if not jobs:
        return fetches, writes
    by_month: dict[str, list[tuple[Job, Future[pd.DataFrame]]]] = defaultdict(list)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for job in jobs:
            by_month[job.month].append((job, pool.submit(_fetch, job, clients)))
        for month in sorted(by_month):
            frames: list[pd.DataFrame] = []
            for job, future in by_month.pop(month):
                error = future.exception()
                if error is not None:
                    fetches.append(FetchResult(job, 0, _describe(error)))
                    logger.error("%s: fetch failed: %s", job.label, _describe(error))
                    continue
                frame = future.result()
                fetches.append(FetchResult(job, len(frame)))
                logger.info("%s: fetched %d rows", job.label, len(frame))
                if not frame.empty:
                    frames.append(frame)
            counts = merge_into_slices(
                table,
                pd.concat(frames, ignore_index=True) if frames else None,
                source=source,
                spec=spec,
            )
            writes.append(
                WriteResult(
                    jobs[0].table, month, counts["days"], counts["unchanged"], counts["rows"]
                )
            )
            logger.info(
                "%s %s: wrote %d slices (%d rows), %d unchanged",
                jobs[0].table,
                month,
                counts["days"],
                counts["rows"],
                counts["unchanged"],
            )
    return fetches, writes


def _parse_symbols(text: str) -> list[str]:
    """Parse and validate a comma-separated ticker list for argparse."""
    symbols = normalize_symbols(text.split(","))
    bad = [symbol for symbol in symbols if not SYMBOL_PATTERN.fullmatch(symbol)]
    if bad or not symbols:
        raise argparse.ArgumentTypeError(
            f"malformed symbols {bad or text!r}: expected 1-6 of A-Z, 0-9, '.', '-' "
            "starting with a letter"
        )
    return symbols


def _parse_tables(text: str) -> list[str]:
    """Parse and validate the ``--tables`` list for argparse."""
    names = list(dict.fromkeys(name.strip() for name in text.split(",") if name.strip()))
    unknown = [name for name in names if name not in TABLES]
    if unknown or not names:
        raise argparse.ArgumentTypeError(f"--tables takes {','.join(TABLES)}, got {text!r}")
    return [name for name in TABLES if name in names]


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Refresh the bronze tables from DoltHub for a window of sessions."
    )
    parser.add_argument("--start", type=date.fromisoformat, help="first date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="last date; default today")
    parser.add_argument(
        "--lookback-sessions",
        type=int,
        default=DEFAULT_LOOKBACK_SESSIONS,
        help="without --start: step back this many sessions from the last session on or "
        "before --end (default %(default)s)",
    )
    parser.add_argument(
        "--symbols",
        type=_parse_symbols,
        help="comma-separated tickers; default the dbt watchlist seed",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="concurrent DoltHub fetches (default %(default)s)",
    )
    parser.add_argument(
        "--tables",
        type=_parse_tables,
        default=list(TABLES),
        help=f"comma-separated subset of {','.join(TABLES)} (default both)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    catalog: Catalog | None = None,
    chain_client: Callable[[], DoltHubClient] = DoltHubClient,
    price_client: Callable[[], DoltHubClient] = stocks_client,
    today: date | None = None,
) -> int:
    """Run the refresh.

    Args:
        argv: Command line without the program name; ``sys.argv[1:]`` when omitted.
        catalog: Iceberg catalog to write to; ``catalog_from_env()`` when omitted.
        chain_client: Creates a client for the ``options`` database; called once per thread.
        price_client: Creates a client for the ``stocks`` database; called once per thread.
        today: The default end date; the current date when omitted.

    Returns:
        0 when every fetch succeeded, 1 when any failed. Bad arguments exit with 2 through
        argparse.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    try:
        start, end = resolve_window(
            args.start,
            args.end,
            lookback_sessions=args.lookback_sessions,
            today=today if today is not None else date.today(),
        )
    except ValueError as error:
        parser.error(str(error))
    symbols: list[str] = args.symbols if args.symbols is not None else read_watchlist()
    bad = [symbol for symbol in symbols if not SYMBOL_PATTERN.fullmatch(symbol)]
    if bad:
        parser.error(f"malformed symbols in the watchlist: {bad}")

    catalog = catalog if catalog is not None else catalog_from_env()
    logger.info(
        "refreshing %s for %d symbols from %s to %s with %d workers",
        ",".join(args.tables),
        len(symbols),
        start,
        end,
        args.workers,
    )
    fetches: list[FetchResult] = []
    writes: list[WriteResult] = []
    if CHAINS in args.tables:
        chains = ensure_table(catalog, table_identifier(spec=OPTION_CHAIN), spec=OPTION_CHAIN)
        f, w = refresh_table(
            chains,
            OPTION_CHAIN,
            CHAIN_SOURCE,
            plan_chain_jobs(start, end, symbols),
            _ThreadClients(chain_client),
            workers=args.workers,
        )
        fetches += f
        writes += w
    if PRICES in args.tables:
        prices = ensure_table(
            catalog, table_identifier(spec=UNDERLYING_PRICE), spec=UNDERLYING_PRICE
        )
        f, w = refresh_table(
            prices,
            UNDERLYING_PRICE,
            PRICE_SOURCE,
            plan_price_jobs(start, end, symbols),
            _ThreadClients(price_client),
            workers=args.workers,
        )
        fetches += f
        writes += w

    summary = summarise(fetches, writes)
    print(summary.line)
    for failure in summary.failures:
        print(f"failed: {failure}", file=sys.stderr)
    return 1 if summary.failures else 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    sys.exit(main())
