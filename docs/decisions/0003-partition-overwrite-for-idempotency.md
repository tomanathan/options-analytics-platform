# 0003. Overwrite the (trade_date, source) slice on every bronze write

Status: Accepted (Phase 1)
Date: 2026-10-05

## Context

Bronze is `bronze.option_chain`, an Iceberg table partitioned by `day(trade_date)` and `identity(source)`. Two sources write to it: DoltHub (history, written by the backfill) and Alpaca (daily snapshots). Each row is tagged with a `source`, and a contract is unique on `(occ_symbol, trade_date, source)`.

Writes will be repeated. A backfill is re-run after a vendor outage. A daily task is retried by Airflow. An operator re-runs one day by hand after a quality failure. A backfill and the daily DAG can also cover the same date. If a write adds rows, each of those repeats duplicates data, and the quality gate, the Phase 2 models and the engine all inherit the duplicates.

The backfill is large (about 11 symbols over roughly 81 months), runs for an hour or more with retries, and will fail partway at least once. Safe repetition is a requirement, not a nicety.

## Decision

Every bronze write replaces the slice it covers. `write_partition` calls `table.overwrite(df, overwrite_filter=trade_date == d AND source == s)`. It never appends. The overwrite is one Iceberg commit: readers see the old slice or the new slice, never a mixture. If another writer commits first, the writer refreshes the table and retries; replacing a slice is idempotent, so a retry is safe.

The unit of replacement is the pair (trade_date, source), not the day. The partition spec matches it: because `source` is a partition field, a slice maps to its own data files, so the overwrite deletes whole files instead of rewriting them, and compaction works per source. (Partitioning by day alone was tried first; pyiceberg's file inspection truncates string bounds to 16 characters, so files could not be mapped to a source reliably.) A DoltHub write for a date does not touch Alpaca rows for the same date, and the reverse. The filter is the same one the uniqueness key implies, so a write cannot leave duplicates behind.

Consequences for callers: a re-run needs no cleanup step and no bookkeeping about what has already landed. To delete a source's day, write an empty frame for that (trade_date, source); the filter removes the old rows and nothing replaces them.

## Consequences

Good:

- Re-running any day, month or the whole history is safe. Retried tasks, overlapping backfills and manual re-runs converge on the same table content.
- The failure mode of a half-finished backfill is a gap, not corruption. Re-running fills it.
- The overwrite is atomic. There is no moment where a day is deleted but not yet rewritten.
- Earlier snapshots stay readable until the maintenance DAG expires them, so a bad overwrite can be inspected (and, within the retention window, compared) through Iceberg time travel.

Costs and risks:

- A partial source response replaces a full day with a partial one. The overwrite does not know the new frame is smaller than the old one. The quality gate therefore has to run on what was written, and the per-underlying row-count check (within 50% of the trailing 20-trading-day median) is the detector. The daily DAG does this: its `quality` task reads the slice back after the write. A failed gate leaves the partial slice in place until the day is re-run; it does not roll back. Phase 1's backfill DAG does not run the gate; after a backfill, compare per-day counts with `make iceberg-count`.
- `ingested_at` changes whenever a slice is rewritten, so two runs over identical vendor data differ in that column. Content comparisons, such as checking a re-run was a no-op, must exclude it; `content_hash` in `oap.ingest.iceberg_writer` does, and `make iceberg-count` prints it. The backfill uses the same hash to skip a slice whose content did not change, so a no-op re-run adds no snapshot.
- Every re-run creates a new Iceberg snapshot and new data files, and the old files stay until snapshots expire. The weekly maintenance DAG expires snapshots older than 7 days and compacts slices that have more than one data file.
- The writer must be given the full slice. Passing only some underlyings for a (trade_date, source) replaces the rest with nothing. The daily DAG passes the whole watchlist in one frame. The backfill may be run for a subset of symbols, so its write task reads the existing slice, keeps the rows of underlyings the run did not request, replaces the rest, and overwrites once; writes run one at a time so two commits never race on the same slice. The quality gate catches a missing underlying through its row-count check once that underlying has five days of history.

## Alternatives considered

**Append, then deduplicate downstream in dbt.** Rejected. Bronze would hold duplicates that every reader has to know about, and the "as received" layer would no longer describe what was received once. Deduplication needs a rule for which copy wins, which is a decision silver would have to make for every re-run. It also lets the quality gate on uniqueness fail on legitimate re-runs, or be removed to stop failing. Storage grows with every retry.

**Merge or upsert on (occ_symbol, trade_date, source).** pyiceberg 0.12 has an upsert, but it works at row level: it compares keys, rewrites the files that contain matched rows, and is slower on a day of tens of thousands of rows. More importantly, it does not remove rows that vanished from the source. If a vendor corrects a day and a contract disappears, upsert keeps the stale row. Slice replacement reproduces the vendor's current answer exactly.

**Delete, then append, as two commits.** Rejected because the two steps are not atomic. A crash or a retry between them leaves the slice missing, and a concurrent reader (or the quality gate) sees an empty day. A single overwrite commit has no such window.
