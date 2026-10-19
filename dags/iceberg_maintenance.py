"""Weekly housekeeping of every bronze Iceberg table: expire old snapshots, compact slices.

Both tasks loop over ``oap.ingest.tables.BRONZE_TABLES`` (``option_chain`` and
``underlying_price``), and both commit, so they run in the one-slot ``bronze_writers`` pool
beside the ingest writers.

``expire_snapshots`` drops snapshots older than seven days from each table's metadata, which
bounds the metadata file and the time-travel window. The current snapshot is always kept, and
a table with no snapshot yet is skipped.
In pyiceberg 0.12 this removes snapshot metadata only: the data files, manifests and manifest
lists those snapshots referenced, and any orphaned files, stay on disk (or in S3). Sweeping
them is a later phase (S3 lifecycle rules and orphan-file removal); until then, storage
grows with every rewrite even though the table only reads live files.

``compact`` rewrites every ``(trade_date, source)`` slice that has more than one live data
file. pyiceberg 0.12 has no ``rewrite_data_files``; instead the slice is read and written back
through ``write_partition``, the same overwrite every ingest uses (ADR 0003). An overwrite of
one slice produces exactly one data file for it, which is all the compaction a table of this
size needs. The rewrite keeps the rows, including their ``ingested_at``, unchanged.
"""

import logging
from datetime import UTC, datetime, timedelta

from airflow.decorators import dag, task

from dags.common import BRONZE_WRITERS_POOL, DEFAULT_ARGS, bronze_table

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
    """Expire snapshots older than a week, then compact multi-file slices, in every bronze table."""

    @task(pool=BRONZE_WRITERS_POOL)
    def expire_snapshots() -> dict[str, int]:
        """Expire snapshots older than the retention; return how many remain per table."""
        from oap.ingest.tables import BRONZE_TABLES

        remaining: dict[str, int] = {}
        for spec in BRONZE_TABLES:
            table = bronze_table(spec)
            if table.current_snapshot() is None:
                logger.info("%s: no snapshots, nothing to expire", spec.name)
                remaining[spec.name] = 0
                continue
            before = len(table.metadata.snapshots)
            table.maintenance.expire_snapshots().older_than(
                datetime.now(UTC) - SNAPSHOT_RETENTION
            ).commit()
            remaining[spec.name] = len(table.refresh().metadata.snapshots)
            logger.info(
                "%s: expired %d snapshots from metadata, %d remain; their data files were "
                "not deleted",
                spec.name,
                before - remaining[spec.name],
                remaining[spec.name],
            )
        return remaining

    @task(pool=BRONZE_WRITERS_POOL)
    def compact() -> dict[str, int]:
        """Rewrite each slice with more than one data file; return how many per table."""
        from oap.ingest.iceberg_writer import (
            partition_file_counts,
            read_partition,
            write_partition,
        )
        from oap.ingest.tables import BRONZE_TABLES

        rewritten: dict[str, int] = {}
        for spec in BRONZE_TABLES:
            table = bronze_table(spec)
            count = 0
            for (trade_date, source), files in sorted(partition_file_counts(table).items()):
                if files <= 1:
                    continue
                frame = read_partition(table, trade_date=trade_date, source=source, spec=spec)
                write_partition(table, frame, trade_date=trade_date, source=source, spec=spec)
                logger.info(
                    "%s: compacted (%s, %s): %d files -> 1", spec.name, trade_date, source, files
                )
                count += 1
            logger.info("%s: compacted %d slices", spec.name, count)
            rewritten[spec.name] = count
        return rewritten

    expire_snapshots() >> compact()


iceberg_maintenance()
