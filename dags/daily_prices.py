"""Daily refresh of the bronze ``underlying_price`` table from DoltHub.

Runs at 16:30 America/New_York on every NYSE session day (``NYSECloseTimetable``) for the
watchlist seed. The session a run is for is the New York date of its ``data_interval_end``.

DoltHub commits a session's bars at about 05:30 UTC on the next day, so at 16:30 on the
session itself its row is not there yet. Each run therefore fetches the last
``LOOKBACK_SESSIONS`` sessions up to and including its own: the previous session, published
overnight, is picked up by this run, and the session's own row appears on the next run (a
one-session lag that fixes itself). The bars are as traded, not adjusted for splits or
dividends (see ``oap.ingest.price_schema``).

Tasks run ``fetch >> write``:

* ``fetch`` pulls the window and stages it as a parquet file. An empty response fails the
  task, because five sessions without a single bar means the feed is stale and should be
  visible, not silently skipped.
* ``write`` merges the staged rows into each day's ``(trade_date, "dolthub_stocks")`` slice in
  the one-slot ``bronze_writers`` pool; slices whose content did not change are not rewritten.

Each task fails without retries on an error retrying cannot fix (``fail_fast``).
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
from dags.datasets import BRONZE_UNDERLYING_PRICE
from dags.timetables import NYSECloseTimetable, session_of

logger = logging.getLogger(__name__)

SOURCE = "dolthub_stocks"
LOOKBACK_SESSIONS = 5


def _session() -> date:
    """Return the session the running task's DAG run is for."""
    return session_of(get_current_context()["data_interval_end"])


@dag(
    dag_id="daily_prices",
    schedule=NYSECloseTimetable(),
    start_date=datetime(2026, 10, 19, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["phase-1", "bronze"],
)
def daily_prices() -> None:
    """Fetch the last few sessions of watchlist prices after the close and merge them in."""

    @task
    @fail_fast
    def fetch() -> str:
        """Pull the trailing window of daily bars from DoltHub and stage it; return the path."""
        from oap.calendar import trading_days
        from oap.ingest.dolthub_stocks import fetch_prices, stocks_client

        session = _session()
        window = trading_days(session - timedelta(days=14), session)[-LOOKBACK_SESSIONS:]
        symbols = read_watchlist()
        frame = fetch_prices(symbols, window[0], session, client=stocks_client())
        if frame.empty:
            raise ValueError(
                f"DoltHub returned no prices for {symbols} from {window[0]} to {session}"
            )
        path = staging_dir("daily_prices") / f"{session.isoformat()}.parquet"
        frame.to_parquet(path, index=False)
        logger.info("staged %d price rows for %s..%s at %s", len(frame), window[0], session, path)
        return str(path)

    @task(pool=BRONZE_WRITERS_POOL, outlets=[BRONZE_UNDERLYING_PRICE])
    @fail_fast
    def write(path: str) -> dict[str, int]:
        """Merge the staged window into the daily price slices; return the counts."""
        import pandas as pd

        from oap.ingest.merge import merge_into_slices
        from oap.ingest.tables import UNDERLYING_PRICE

        counts = merge_into_slices(
            bronze_table(UNDERLYING_PRICE),
            pd.read_parquet(path, dtype_backend="pyarrow"),
            source=SOURCE,
            spec=UNDERLYING_PRICE,
        )
        logger.info(
            "wrote %d slices (%d rows), %d unchanged",
            counts["days"],
            counts["rows"],
            counts["unchanged"],
        )
        return counts

    # TaskFlow resolves XComArgs to their values at run time, which mypy cannot see.
    write(fetch())  # type: ignore[arg-type]


daily_prices()
