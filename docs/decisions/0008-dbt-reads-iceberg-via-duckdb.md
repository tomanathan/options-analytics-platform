# 0008. dbt reads the Iceberg bronze tables through DuckDB, pinned per run

Status: Accepted (Phase 2)
Date: 2026-10-19

## Context

Bronze is two Iceberg tables in a local SQLite catalog (ADR 0005), written by the Airflow containers. Their metadata records container-absolute paths (`file:///opt/airflow/.iceberg-local/...`). dbt runs on DuckDB for local work and CI (ADR 0002) and on Snowflake for production. Phase 2 needs dbt to build silver and gold from the real bronze tables on a laptop, with no Snowflake account, from three places: the `dbt_build` DAG in the Airflow container, `make dbt-build-local` on the host, and `make check`, which has no vendor data at all.

Four requirements follow. dbt must read the table version the catalog says is committed, not a file that happens to exist. The models and their tests must see one snapshot even if an ingest task commits during the run. The DAG run must work without network access. And CI must exercise the same read path without vendor data.

## Decision

A macro, `register_bronze` in `dbt/macros/register_bronze.sql`, runs as an `on-run-start` hook (`dbt_project.yml`). On the `dev` (DuckDB) target it does four things.

1. It loads the DuckDB `iceberg` and `sqlite` extensions and opens the catalog file with `sqlite_scan`, reading `metadata_location` for each bronze table from the catalog's `iceberg_tables` table. The committed metadata file is, by definition, the one in that column.
2. It pins that metadata version for the whole run. It creates the views `bronze.option_chain` and `bronze.underlying_price` as `iceberg_scan('<dir>/warehouse/bronze/<table>', version = '<metadata file stem>', allow_moved_paths = true)`. `allow_moved_paths` makes DuckDB resolve the container-absolute paths in the metadata against the table directory it was given, so the host and the container read the same files. The models and their tests read the views, so they read the same snapshot.
3. It records the pinned `metadata_location` and the mode in `bronze.registered_snapshot`.
4. It fails closed. A missing catalog file, a missing table or an unknown mode raises a compiler error. There is no fallback to another source.

`OAP_DBT_SOURCE` selects the catalog. `iceberg` reads `OAP_ICEBERG_LOCAL_DIR` (default `.iceberg-local`), `synthetic` reads `OAP_SYNTHETIC_BRONZE_DIR` (default `.dbt-local/synthetic-iceberg`), and `auto` (the default) uses `iceberg` if its `catalog.db` exists and `synthetic` otherwise. The synthetic catalog is written by `scripts/make_synthetic_bronze.py` through the real writer (`ensure_table`, `write_partition`), so `make check` and CI take the same `iceberg_scan` path as a real run. A mode lock in `bronze.registered_snapshot` stops a DuckDB file built from one mode from being built from the other, so synthetic rows can never reach `oap.duckdb`. The `dbt_build` DAG sets `iceberg` explicitly and the Make targets set the mode they mean.

The hook does nothing on other targets, and it is skipped for `compile`, `parse`, `list` and `docs`, because dbt 1.12 runs `on-run-start` hooks for those commands too. On Snowflake the sources point at `OAP_SNOWFLAKE_BRONZE_DATABASE` and `OAP_SNOWFLAKE_BRONZE_SCHEMA`, which have to hold the bronze tables. Nothing in `infra/` creates them yet.

## Consequences

Good:

- dbt builds on the real bronze tables on a laptop. A full build with tests took about 12 seconds on 1.48 million option rows.
- The build and its tests agree on the data even while a backfill commits. A commit that lands mid-run is picked up by the next run.
- `make check` runs the real read path on deterministic synthetic data, with expected row counts asserted by `assert_synthetic_row_counts`.
- The DAG run is offline: the extensions and dbt packages are baked into the image (ADR 0006).

Costs and risks:

- The hook depends on the layout of the local catalog (`iceberg_tables`, `metadata_location`) and on the warehouse path convention `<dir>/warehouse/bronze/<table>`. A catalog with another layout needs the macro changed.
- Only one process may write a DuckDB file. `max_active_runs=1` protects `dbt_build` from itself; it does not stop `make dbt-build-local` from colliding with a running DAG.
- The macro is DuckDB-specific and the Snowflake path is untested: the models use portable SQL (ADR 0002), but no Snowflake account has run them.
- The pin is a metadata file, not an Iceberg snapshot id. The recorded value in `bronze.registered_snapshot` is a path.

## Alternatives considered

**Export bronze to Parquet, then point dbt at the files.** Rejected. It adds a job and a second copy of the data that can go stale, and the copy is no longer the table the writers commit to. The export would have to decide which files are live, which is the question Iceberg metadata already answers.

**Version guessing (`unsafe_enable_version_guessing`).** Rejected. DuckDB then picks a metadata file by looking at the directory. A failed or concurrent commit can leave a metadata file that the catalog never pointed at (an orphan), and the highest-numbered file may be that one. dbt would build from data no reader of the table ever saw. Reading the catalog's own `metadata_location` removes the guess.

**A REST catalog service.** Rejected, for the reason ADR 0005 gave for ingest: one more service to run for a one-developer project, and it would still need a way to hand dbt a consistent snapshot.

**Require Snowflake to build silver and gold.** Rejected. It needs credentials for every run, trials expire (ADR 0002), and CI would have nothing to build on. Snowflake stays the production target.
