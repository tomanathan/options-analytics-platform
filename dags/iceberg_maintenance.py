"""Weekly housekeeping of the bronze Iceberg table: expire old snapshots, compact slices.

``expire_snapshots`` drops snapshots older than seven days from the table metadata, which
bounds the metadata file and the time-travel window. The current snapshot is always kept.

``compact`` rewrites every ``(trade_date, source)`` slice that has more than one live data
file. pyiceberg 0.12 has no ``rewrite_data_files``; instead the slice is read and written back
through ``write_partition``, the same overwrite every ingest uses (ADR 0003). An overwrite of
one slice produces exactly one data file for it, which is all the compaction a table of this
size needs. The rewrite keeps the rows, including their ``ingested_at``, unchanged.
"""

import logging
from datetime import UTC, datetime, timedelta

from airflow.decorators import dag, task

from dags.common import DEFAULT_ARGS, bronze_table

logger = logging.getLogger(__name__)

SNAPSHOT_RETENTION = timedelta(days=7)


@dag(
    dag_id="iceberg_maintenance",
    schedule="@weekly",
    start_date=datetime(2026, 10, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["phase-1", "maintenance"],
)
def iceberg_maintenance() -> None:
    """Expire snapshots older than a week, then compact multi-file slices."""

    @task
    def expire_snapshots() -> int:
        """Expire snapshots older than the retention; return how many remain."""
        table = bronze_table()
        before = len(table.metadata.snapshots)
        table.maintenance.expire_snapshots().older_than(
            datetime.now(UTC) - SNAPSHOT_RETENTION
        ).commit()
        remaining = len(table.refresh().metadata.snapshots)
        logger.info("expired %d snapshots, %d remain", before - remaining, remaining)
        return remaining

    @task
    def compact() -> int:
        """Rewrite each slice with more than one data file; return how many were rewritten."""
        from oap.ingest.iceberg_writer import (
            partition_file_counts,
            read_partition,
            write_partition,
        )

        table = bronze_table()
        rewritten = 0
        for (trade_date, source), files in sorted(partition_file_counts(table).items()):
            if files <= 1:
                continue
            frame = read_partition(table, trade_date=trade_date, source=source)
            write_partition(table, frame, trade_date=trade_date, source=source)
            logger.info("compacted (%s, %s): %d files -> 1", trade_date, source, files)
            rewritten += 1
        logger.info("compacted %d slices", rewritten)
        return rewritten

    expire_snapshots() >> compact()


iceberg_maintenance()
