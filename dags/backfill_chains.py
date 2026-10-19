"""Backfill DoltHub option chain history into the bronze Iceberg table.

Triggered by hand (``make backfill START=... END=... [SYMBOLS=...]``) with ``start`` and
``end`` dates; ``end`` has no default on purpose, because a default computed at parse time
would change every time the scheduler parses the file. An empty ``symbols`` list means the
watchlist seed (``dbt/seeds/watchlist.csv``).

Tasks:

* ``plan`` lists one fetch job per (symbol, month) from the NYSE calendar, so months without
  a session produce no job; ``plan_months`` groups them into one write job per month.
* ``fetch_month`` (mapped per symbol and month, four at a time) pulls the month from DoltHub
  and stages it as a parquet file. It is skipped when DoltHub has no rows for it.
* ``write_month`` (mapped per month, one at a time, in the one-slot ``bronze_writers`` pool
  so it never commits alongside the daily DAG) merges the staged symbols into each
  day's ``(trade_date, "dolthub")`` slice through ``oap.ingest.merge.merge_into_slices``,
  which also stamps ``ingested_at`` with the write time.
* ``summarize`` logs the totals.

Every task fails at once, without retries, on an error that retrying cannot fix (see
``fail_fast``), and ``plan`` rejects malformed symbols before any month is fetched.

Fetching and writing are separate because a bronze slice holds every underlying of a day:
writing one symbol's rows on their own would replace the other symbols' rows (ADR 0003).
``write_month`` therefore reads the slice (``merge_into_slices``), replaces the rows of each
underlying that DoltHub returned rows for on that day, keeps every other row and overwrites
the slice once. Absence
is not information: a symbol whose fetch came back empty (a month with no data, or a
transient empty response) keeps the rows already loaded for it, matching the daily DAG,
which refuses an empty response rather than wiping a slice. Writes
run one at a time so concurrent commits never race on the same slice, and a slice whose
content did not change is not rewritten, which keeps a re-run from adding snapshots.
``write_month`` waits for every fetch to finish; a month with a failed fetch fails its
write and leaves its slices untouched, while complete months are still written.
"""

import logging
import shutil
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

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
from dags.datasets import BRONZE_OPTION_CHAIN

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

SOURCE = "dolthub"


def _session_dates(frame: "pd.DataFrame") -> "pd.Series[Any]":
    """Return a frame's ``trade_date`` column as ``datetime.date`` values, whatever its dtype."""
    import pandas as pd

    return pd.to_datetime(frame["trade_date"].astype(str)).dt.date


def plan_jobs(start: date, end: date, symbols: Sequence[str]) -> list[dict[str, str]]:
    """List one fetch job per (symbol, month) with at least one NYSE session in range.

    Args:
        start: First calendar date to backfill, inclusive.
        end: Last calendar date to backfill, inclusive.
        symbols: Tickers to backfill; the watchlist seed when empty.

    Returns:
        Jobs ordered by month, then symbol, each ``{"symbol", "start", "end"}`` with ISO dates
        that are the first and last session of the month within the range.

    Raises:
        ValueError: If ``start`` is after ``end``, a symbol is not a string, or a symbol is not
            a well-formed ticker (checked here so a typo fails the plan, not every fetch).
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
        {"symbol": symbol, "start": chunk[0].isoformat(), "end": chunk[-1].isoformat()}
        for chunk in month_chunks(trading_days(start, end))
        for symbol in tickers
    ]


def month_jobs(jobs: Sequence[dict[str, str]]) -> list[dict[str, Any]]:
    """Group fetch jobs into one write job per month.

    Args:
        jobs: Output of ``plan_jobs``.

    Returns:
        ``{"month": "YYYY-MM", "start", "end", "symbols"}`` per month, in month order.
    """
    months: dict[str, dict[str, Any]] = {}
    for job in jobs:
        month = job["start"][:7]
        entry = months.setdefault(
            month, {"month": month, "start": job["start"], "end": job["end"], "symbols": []}
        )
        entry["symbols"].append(job["symbol"])
    return list(months.values())


@dag(
    dag_id="backfill_chains",
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
def backfill_chains() -> None:
    """Load DoltHub history for a date range into bronze, one slice per session day."""

    @task
    @fail_fast
    def plan() -> list[dict[str, str]]:
        """Build the (symbol, month) fetch jobs from the run's params."""
        params = get_current_context()["params"]
        jobs = plan_jobs(
            date.fromisoformat(params["start"]),
            date.fromisoformat(params["end"]),
            params["symbols"],
        )
        logger.info("planned %d fetch jobs", len(jobs))
        return jobs

    @task
    def plan_months(jobs: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Group the fetch jobs into one write job per month."""
        return month_jobs(jobs)

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
    def fetch_month(job: dict[str, str]) -> dict[str, Any]:
        """Fetch one symbol's month from DoltHub and stage it as parquet."""
        from oap.ingest.dolthub import DoltHubClient, fetch_chain

        context = get_current_context()
        month = job["start"][:7]
        target = staging_dir("backfill", context["run_id"], month)
        frame = fetch_chain(
            job["symbol"],
            date.fromisoformat(job["start"]),
            date.fromisoformat(job["end"]),
            client=DoltHubClient(),
        )
        if frame.empty:
            (target / f"{job['symbol']}.empty").touch()
            raise AirflowSkipException(f"DoltHub has no rows for {job['symbol']} in {month}")
        partial = target / f"{job['symbol']}.parquet.partial"
        frame.to_parquet(partial, index=False)
        # Rename last so write_month never reads a half-written file.
        partial.replace(target / f"{job['symbol']}.parquet")
        days = _session_dates(frame).nunique()
        return {"symbol": job["symbol"], "month": month, "days": days, "rows": len(frame)}

    @task(
        trigger_rule=TriggerRule.ALL_DONE,
        max_active_tis_per_dag=1,
        pool=BRONZE_WRITERS_POOL,
        sla=None,
    )
    @fail_fast
    def write_month(job: dict[str, Any]) -> dict[str, Any]:
        """Merge one month's staged symbols into its daily slices and overwrite them."""
        import pandas as pd

        from oap.ingest.merge import merge_into_slices
        from oap.ingest.tables import OPTION_CHAIN

        context = get_current_context()
        source_dir = staging_dir("backfill", context["run_id"], job["month"])
        symbols: list[str] = job["symbols"]
        frames = []
        missing = []
        for symbol in symbols:
            staged = source_dir / f"{symbol}.parquet"
            if staged.exists():
                frames.append(pd.read_parquet(staged, dtype_backend="pyarrow"))
            elif not (source_dir / f"{symbol}.empty").exists():
                missing.append(symbol)
        if missing:
            # Retrying cannot help: the fetches are finished. Re-run the DAG for this month.
            raise AirflowFailException(f"{job['month']}: fetch failed for {', '.join(missing)}")

        if frames:
            counts = merge_into_slices(
                bronze_table(),
                pd.concat(frames, ignore_index=True),
                source=SOURCE,
                spec=OPTION_CHAIN,
            )
        else:
            counts = {"days": 0, "unchanged": 0, "rows": 0}
        shutil.rmtree(source_dir, ignore_errors=True)
        logger.info(
            "%s: wrote %d slices (%d rows), %d unchanged",
            job["month"],
            counts["days"],
            counts["rows"],
            counts["unchanged"],
        )
        return {"month": job["month"], **counts}

    @task(trigger_rule=TriggerRule.NONE_FAILED, outlets=[BRONZE_OPTION_CHAIN])
    def summarize(results: Sequence[dict[str, Any]]) -> dict[str, int]:
        """Log the totals of the run."""
        totals = {"months": 0, "days": 0, "unchanged": 0, "rows": 0}
        for result in results:
            totals["months"] += 1
            totals["days"] += int(result["days"])
            totals["unchanged"] += int(result["unchanged"])
            totals["rows"] += int(result["rows"])
        logger.info(
            "backfill wrote %(rows)d rows to %(days)d slices over %(months)d months; "
            "%(unchanged)d slices were already up to date",
            totals,
        )
        return totals

    # TaskFlow resolves XComArgs to their values at run time, which mypy cannot see.
    jobs = plan()
    fetched = fetch_month.expand(job=jobs)
    written = write_month.expand(job=plan_months(jobs))  # type: ignore[arg-type]
    fetched >> written
    summarize(written)  # type: ignore[arg-type]


backfill_chains()
