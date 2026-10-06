# 0005. A standard-library SQLite catalog for local Iceberg

Status: Accepted (Phase 1)
Date: 2026-10-05

## Context

Bronze needs an Iceberg catalog that works on a laptop with no AWS account, in tests, and inside the Airflow containers, where the DAGs run. pyiceberg's `SqlCatalog` is the obvious choice for a local catalog, but it requires SQLAlchemy 2.0 or later. Airflow 2.11.2 pins SQLAlchemy below 2.0. The two cannot share one environment, and the local catalog must work inside the Airflow image, which is where ingest runs.

## Decision

Add `src/oap/ingest/local_catalog.py`: a small pyiceberg `MetastoreCatalog` subclass built on the standard library's `sqlite3` module. It writes exactly the table layout `SqlCatalog` uses (`iceberg_tables` and `iceberg_namespace_properties`), so the `catalog.db` file stays readable by `SqlCatalog` anywhere SQLAlchemy 2 is available.

`OAP_ICEBERG_CATALOG=sql` (the default; `local` is an alias) selects it. Production uses Glue (`OAP_ICEBERG_CATALOG=glue`), which does not need SQLAlchemy. The Airflow image installs pyiceberg without the `sql-sqlite` extra for the same reason.

## Consequences

- We own about 150 lines of catalog code, with tests. They cover namespaces and tables only; views are not supported.
- Single-writer local use. Commits are optimistic (the row is updated only if its metadata location is unchanged) and SQLite serialises writes, so concurrent Airflow tasks on one host are safe, but the file must not be shared across hosts or over a network mount.
- A local catalog file can be opened with `SqlCatalog` from another environment for inspection.
- Remove the module when the project moves to Airflow 3, which uses SQLAlchemy 2, and use `SqlCatalog` directly.

## Alternatives considered

**Pin SQLAlchemy 2.** Rejected. Airflow 2.11 does not support it and would break its own metadata layer.

**Separate dependency groups with declared conflicts.** Rejected. It means two environments, and the Airflow container would still have no local catalog, which is the place that needs one.

**A REST catalog container for local development.** Rejected for now. It adds a service to run for a one-developer project. Revisit if a second writer appears.

**Glue mocked with moto in tests.** Rejected. It helps tests but leaves the container with no catalog to write to without AWS.
