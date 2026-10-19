"""Backfill DoltHub daily prices into the bronze ``underlying_price`` Iceberg table.

Triggered by hand with ``start`` and ``end`` dates; ``end`` has no default on purpose, because
a default computed at parse time would change every time the scheduler parses the file. An
empty ``symbols`` list means the watchlist seed (``dbt/seeds/watchlist.csv``).

Tasks:

* ``plan`` lists one job per month from the NYSE calendar (``plan_months``), so months
  without a session produce no job. A job carries every symbol, because DoltHub answers a
  month for the whole watchlist in one query of a couple of hundred rows.
* ``fetch_month`` (mapped per month, four at a time) pulls the month from the DoltHub
  ``stocks`` database and stages it as a parquet file. It is skipped when DoltHub has no rows.
* ``write_month`` (mapped per month, one at a time, in the one-slot ``bronze_writers`` pool)
  merges the staged rows into each day's ``(trade_date, "dolthub_stocks")`` slice and writes
  it with ``write_partition``.
* ``summarize`` logs the totals.

DoltHub commits the bars of a session at about 05:30 UTC on the next day, so a range that
ends on the last completed session may lack its final bar; run it again later. Prices are
stored as traded, **not adjusted** for splits or dividends: AAPL closes 499.23 on 2020-08-28
and 129.04 on 2020-08-31. That matches the option strikes quoted on the same date; a return
series must apply DoltHub's ``split`` table downstream.

Merge semantics are those of ``oap.ingest.merge``: a bronze slice holds every underlying of a
day, so ``write_month`` replaces only the underlyings DoltHub returned rows for, keeps every
other row, and skips a slice whose content did not change (a re-run adds no snapshots).
Absence is not deletion: an empty or partial response never removes rows already loaded.
``write_month`` waits for every fetch; a month whose fetch failed fails its write and leaves
its slices untouched, while complete months are still written.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.models.param import Param
from airflow.operators.python import get_current_context
from airflow.utils.trigger_rule import TriggerRule

from dags.common import (
    BRONZE_WRITERS_POOL,
    DEFAULT_ARGS,
    bronze_table,
    fail_fast,
    normalize_symbols,
    read_watchlist,
    staging_dir,
)
from dags.datasets import BRONZE_UNDERLYING_PRICE

logger = logging.getLogger(__name__)

SOURCE = "dolthub_stocks"


def plan_months(start: date, end: date, symbols: Sequence[str]) -> list[dict[str, Any]]:
    """List one fetch-and-write job per month with at least one NYSE session in range.

    Args:
        start: First calendar date to backfill, inclusive.
        end: Last calendar date to backfill, inclusive.
        symbols: Tickers to backfill; the watchlist seed when empty.

    Returns:
        Jobs in month order, each ``{"month": "YYYY-MM", "start", "end", "symbols"}`` where
        ``start`` and ``end`` are the ISO dates of the first and last session of the month
        within the range and ``symbols`` are the cleaned tickers.

    Raises:
        ValueError: If ``start`` is after ``end``, a symbol is not a string, or a symbol is
            not a well-formed ticker (checked here so a typo fails the plan, not every fetch).
    """
    from oap.calendar import trading_days
    from oap.ingest.dolthub import SYMBOL_PATTERN, month_chunks

    not_strings = [symbol for symbol in symbols if not isinstance(symbol, str)]
    if not_strings:
        raise ValueError(f"symbols must be strings, got {not_strings!r}")
    tickers = normalize_symbols(symbols) or read_watchlist()
    bad = [symbol for symbol in tickers if not SYMBOL_PATTERN.fullmatch(symbol)]
    if bad:
        raise ValueError(
            f"malformed symbols {bad}: expected 1-6 of A-Z, 0-9, '.', '-' starting with a letter"
        )
    return [
        {
            "month": f"{chunk[0]:%Y-%m}",
            "start": chunk[0].isoformat(),
            "end": chunk[-1].isoformat(),
            "symbols": list(tickers),
        }
        for chunk in month_chunks(trading_days(start, end))
    ]


@dag(
    dag_id="backfill_prices",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    default_args=DEFAULT_ARGS,
    max_active_tasks=4,
    # Two runs over overlapping months would race on the same slices.
    max_active_runs=1,
    params={
        "start": Param("2020-01-01", type="string", format="date"),
        "end": Param(type="string", format="date", description="Last date, inclusive"),
        "symbols": Param([], type="array", description="empty = watchlist seed"),
    },
    tags=["phase-1", "bronze"],
)
def backfill_prices() -> None:
    """Load DoltHub daily prices for a date range into bronze, one slice per session day."""

    @task
    @fail_fast
    def plan() -> list[dict[str, Any]]:
        """Build the per-month jobs from the run's params."""
        params = get_current_context()["params"]
        jobs = plan_months(
            date.fromisoformat(params["start"]),
            date.fromisoformat(params["end"]),
            params["symbols"],
        )
        logger.info("planned %d monthly jobs", len(jobs))
        return jobs

    # DoltHub's free API throttles and drops connections under load; a month is cheap to
    # refetch, so this task retries more, and with longer backoff, than DEFAULT_ARGS.
    # Airflow rejects an SLA on mapped tasks, hence sla=None here and on write_month.
    @task(
        retries=5,
        retry_exponential_backoff=True,
        max_retry_delay=timedelta(minutes=10),
        sla=None,
    )
    @fail_fast
    def fetch_month(job: dict[str, Any]) -> dict[str, Any]:
        """Fetch one month of prices for every symbol and stage it as parquet."""
        from oap.ingest.dolthub_stocks import fetch_prices, stocks_client

        context = get_current_context()
        month = job["month"]
        target = staging_dir("prices", context["run_id"])
        frame = fetch_prices(
            job["symbols"],
            date.fromisoformat(job["start"]),
            date.fromisoformat(job["end"]),
            client=stocks_client(),
        )
        if frame.empty:
            (target / f"{month}.empty").touch()
            raise AirflowSkipException(f"DoltHub has no price rows for {month}")
        partial = target / f"{month}.parquet.partial"
        frame.to_parquet(partial, index=False)
        # Rename last so write_month never reads a half-written file.
        partial.replace(target / f"{month}.parquet")
        return {"month": month, "rows": len(frame), "days": int(frame["trade_date"].nunique())}

    @task(
        trigger_rule=TriggerRule.ALL_DONE,
        max_active_tis_per_dag=1,
        pool=BRONZE_WRITERS_POOL,
        sla=None,
    )
    @fail_fast
    def write_month(job: dict[str, Any]) -> dict[str, Any]:
        """Merge one month's staged prices into its daily slices and overwrite them."""
        import pandas as pd

        from oap.ingest.merge import merge_into_slices
        from oap.ingest.tables import UNDERLYING_PRICE

        context = get_current_context()
        month = job["month"]
        source_dir = staging_dir("prices", context["run_id"])
        staged = source_dir / f"{month}.parquet"
        marker = source_dir / f"{month}.empty"
        if staged.exists():
            counts = merge_into_slices(
                bronze_table(UNDERLYING_PRICE),
                pd.read_parquet(staged, dtype_backend="pyarrow"),
                source=SOURCE,
                spec=UNDERLYING_PRICE,
            )
        elif marker.exists():
            counts = {"days": 0, "unchanged": 0, "rows": 0}
        else:
            # Retrying cannot help: the fetch is finished. Re-run the DAG for this month.
            raise AirflowFailException(f"{month}: fetch failed")
        staged.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        logger.info(
            "%s: wrote %d slices (%d rows), %d unchanged",
            month,
            counts["days"],
            counts["rows"],
            counts["unchanged"],
        )
        return {"month": month, **counts}

    @task(trigger_rule=TriggerRule.NONE_FAILED, outlets=[BRONZE_UNDERLYING_PRICE])
    def summarize(results: Sequence[dict[str, Any]]) -> dict[str, int]:
        """Log the totals of the run."""
        totals = {"months": 0, "days": 0, "unchanged": 0, "rows": 0}
        for result in results:
            totals["months"] += 1
            totals["days"] += int(result["days"])
            totals["unchanged"] += int(result["unchanged"])
            totals["rows"] += int(result["rows"])
        logger.info(
            "price backfill wrote %(rows)d rows to %(days)d slices over %(months)d months; "
            "%(unchanged)d slices were already up to date",
            totals,
        )
        return totals

    # TaskFlow resolves XComArgs to their values at run time, which mypy cannot see.
    jobs = plan()
    fetched = fetch_month.expand(job=jobs)
    written = write_month.expand(job=jobs)
    fetched >> written
    summarize(written)  # type: ignore[arg-type]


backfill_prices()
