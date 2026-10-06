# 0001. Medallion layering with Iceberg bronze on S3

Status: Accepted (Phase 0)
Date: 2026-10-05

## Context

The platform ingests a daily snapshot of every listed option contract for a watchlist of underlyings. A single underlying has thousands of contracts per day, and the planned intraday phase multiplies that. Three requirements drive the storage design.

First, raw history must be kept in full and replayable. The spread engine calibrates its implied probability distribution against realized outcomes from 2019 onward. When a parsing rule or a data fix changes, the calibration has to be re-run against the same raw inputs, and an earlier result has to be reproducible exactly as it was run.

Second, the vendor schema will change. Alpaca adds fields over time, and we will add derived columns. Old data must stay readable without rewriting it.

Third, the modeling layer is Snowflake with dbt, which is the stack this project is meant to exercise, while ingest runs in Airflow outside Snowflake. The raw layer therefore has to be readable from both Python and Snowflake.

## Decision

Use a medallion layout with three layers.

- **Bronze** is raw option chains stored as Apache Iceberg tables on S3, registered in the AWS Glue Data Catalog in the `oap_bronze` database. Rows are kept as received, loaded idempotently per snapshot date, so a re-run replaces that date's partition and the earlier Iceberg snapshot stays readable.
- **Silver** is cleaned and typed data in Snowflake, built by dbt from bronze.
- **Gold** is analysis-ready data in Snowflake, built by dbt from silver, and is what the spread engine reads.

Great Expectations validates data at each layer boundary before the next layer is built. Terraform provisions the bucket and Glue database; the bucket keeps the `bronze/` prefix in STANDARD storage for 30 days, then moves it to STANDARD_IA.

Phase 0 creates the bucket, the Glue database and the IAM user. No Iceberg tables exist yet; Phase 1 adds them.

## Consequences

Good:

- Schema evolution is a metadata operation. Adding or renaming a column does not rewrite old files, so a vendor change does not force a backfill.
- Iceberg snapshots give time travel for as long as we retain them. A calibration run can record the snapshot id it read and be reproduced later. Snowflake Time Travel would not serve here: it is capped at 90 days, and the calibration window starts in 2019.
- The Glue Catalog is the interop point. Python writers (PyIceberg) and Snowflake (through an external volume and a Glue catalog integration) see the same tables, and Athena remains available for ad hoc inspection.
- Raw history stays on S3 object pricing, with lifecycle tiering, instead of Snowflake storage. Reprocessing raw data does not require a running warehouse.

Costs:

- Two systems to operate. Bronze maintenance (compaction, snapshot expiry) is our job; Snowflake does not do it for tables it only reads.
- Snowflake reads bronze as externally managed Iceberg tables. That needs an external volume, a catalog integration and an IAM trust relationship, none of which exist in Phase 0. The IAM user Terraform creates is for the ingest writer, not for Snowflake.
- Iceberg tables from a Glue catalog have a refresh lag in Snowflake. Gates must read the same snapshot the transform used, not "latest".
- Small files will accumulate if Phase 1 writes one batch per underlying per day. Writes should be batched, and compaction scheduled.

## Alternatives considered

**Land raw data directly in Snowflake stages or tables.** Simplest to run, and one fewer system. Rejected because raw history would then live only inside the warehouse. Reprocessing needs compute for every replay, Time Travel retention is bounded, and moving to another engine later means exporting everything. Keeping the raw layer outside Snowflake also keeps the warehouse bill proportional to modeled data, not to every contract we ever fetched.

**Delta Lake.** A sound table format with similar features. Rejected because Snowflake reads Iceberg as a first-class external table type with a Glue catalog integration, while Delta support goes through external tables or UniForm metadata generation, which adds a layer we would have to maintain. Delta's advantages mostly show up with Spark or Databricks, which this project does not use.

**Plain Parquet on S3 without a table format.** Cheapest and easiest to start. Rejected because it gives us none of the properties above. Schema changes need a convention and rewrites, there are no snapshots, so reproducing a past calibration means keeping copies by hand, and a reader can see a half-written batch. We would rebuild a table format, badly.
