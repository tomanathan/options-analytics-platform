"""Daily end-of-day option chain snapshot from Alpaca into the bronze Iceberg table.

Runs at 16:30 America/New_York on every NYSE session day (``NYSECloseTimetable``) for the
watchlist seed. The session a run is for is the New York date of its ``data_interval_end``.

The snapshot comes from Alpaca's free ``indicative`` feed: quotes are derived from OPRA
rather than the consolidated NBBO, and there is no open interest. It is stored as
``source="alpaca_indicative"`` so it is never mistaken for a real NBBO record. The endpoint
only returns the latest snapshot, so a session can only be captured on its own evening.
``snapshot_chain`` enforces this: when the newest quote's New York date is not the run's
session (for example a manual trigger the next morning), it raises ``AlpacaError`` and
``snapshot`` fails before anything is written, rather than storing live quotes under an
earlier session's date.

Tasks run ``snapshot >> quality >> write``:

* ``snapshot`` pulls the chain and stages it as a parquet file (a DataFrame never travels
  through XCom). An empty response fails the task rather than wiping the day's slice.
* ``quality`` runs the bronze suite on the staged frame against the previous 20 sessions of
  the same source, before anything is committed, and returns the staged path.
* ``write`` overwrites the ``(session, "alpaca_indicative")`` slice with the staged file, in
  the one-slot ``bronze_writers`` pool, then reads the slice back and checks its row count
  against what it wrote. It is the task that updates the ``BRONZE_OPTION_CHAIN`` Dataset, so
  ``dbt_build`` is triggered only by a slice that passed the gate and landed.

Each task fails without retries on an error retrying cannot fix (``fail_fast``).

The gate runs before the write, as ADR 0003 (amended) decides: a slice that fails it must not
be published, because ``dbt_build`` and the analytics read bronze as soon as it is committed.
A failure fails the run before the slice is touched, so the previous slice of the session, if
any, stays in place and the run can be repeated. The staged file is the exact frame ``write``
commits, so the gate inspects what will be written; the read-back row count after the write
is a second, cheap check that the commit holds that frame.
"""

import logging
from datetime import UTC, date, datetime, timedelta

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

from dags.common import (
    BRONZE_WRITERS_POOL,
    DEFAULT_ARGS,
    bronze_table,
    fail_fast,
    read_watchlist,
    staging_dir,
)
from dags.datasets import BRONZE_OPTION_CHAIN
from dags.timetables import NYSECloseTimetable, session_of

logger = logging.getLogger(__name__)

SOURCE = "alpaca_indicative"
HISTORY_SESSIONS = 20


def _session() -> date:
    """Return the session the running task's DAG run is for."""
    return session_of(get_current_context()["data_interval_end"])


@dag(
    dag_id="daily_chain_snapshot",
    schedule=NYSECloseTimetable(),
    start_date=datetime(2026, 10, 6, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["phase-1", "bronze"],
)
def daily_chain_snapshot() -> None:
    """Snapshot the watchlist's option chains after the close, gate them, then write them."""

    @task
    @fail_fast
    def snapshot() -> str:
        """Pull the watchlist chains from Alpaca and stage them; return the parquet path."""
        from oap.ingest.alpaca import AlpacaClient, snapshot_chain

        session = _session()
        symbols = read_watchlist()
        frame = snapshot_chain(symbols, as_of=session, client=AlpacaClient.from_env())
        if frame.empty:
            raise ValueError(f"Alpaca returned no contracts for {symbols} on {session}")
        path = staging_dir("daily") / f"{session.isoformat()}.parquet"
        frame.to_parquet(path, index=False)
        logger.info("staged %d contracts for %s at %s", len(frame), session, path)
        return str(path)

    @task
    @fail_fast
    def quality(path: str) -> str:
        """Run the bronze suite on the staged slice; BronzeQualityError fails the task.

        Returns:
            The staged parquet path, unchanged, so ``write`` runs after the gate.
        """
        import pandas as pd

        from oap.calendar import previous_trading_day, trading_days
        from oap.ingest.iceberg_writer import read_range
        from oap.quality.bronze_suite import assert_bronze_ok

        session = _session()
        frame = pd.read_parquet(path, dtype_backend="pyarrow")
        last = previous_trading_day(session)
        # 20 sessions always fit in 45 calendar days, holidays included.
        window = trading_days(last - timedelta(days=45), last)[-HISTORY_SESSIONS:]
        history = read_range(bronze_table(), start=window[0], end=last, source=SOURCE)
        assert_bronze_ok(frame, history)
        logger.info("bronze suite passed for (%s, %s): %d rows", session, SOURCE, len(frame))
        return path

    @task(pool=BRONZE_WRITERS_POOL, outlets=[BRONZE_OPTION_CHAIN])
    @fail_fast
    def write(path: str) -> int:
        """Overwrite the session's slice with the gated snapshot; return the row count."""
        import pandas as pd

        from oap.ingest.iceberg_writer import read_partition, write_partition

        session = _session()
        table = bronze_table()
        frame = pd.read_parquet(path, dtype_backend="pyarrow")
        rows = write_partition(table, frame, trade_date=session, source=SOURCE)
        stored = len(read_partition(table, trade_date=session, source=SOURCE))
        if stored != rows:
            raise ValueError(f"wrote {rows} rows but the slice holds {stored}")
        logger.info("wrote %d rows to (%s, %s)", rows, session, SOURCE)
        return rows

    # TaskFlow resolves XComArgs to their values at run time, which mypy cannot see.
    write(quality(snapshot()))  # type: ignore[arg-type]


daily_chain_snapshot()
