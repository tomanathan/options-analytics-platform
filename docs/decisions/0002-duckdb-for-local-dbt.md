# 0002. DuckDB as the local and CI dbt target

Status: Accepted (Phase 0)
Date: 2026-10-05

## Context

`dbt compile` against the Snowflake adapter opens a connection, because dbt introspects the warehouse while resolving relations and macros. That needs live credentials and a running warehouse. Two things break as a result.

CI cannot run `dbt compile` on a pull request without storing Snowflake credentials as repository secrets. A pull request from a fork would not have them at all.

Local work needs a trial account even to check that a model parses and its refs resolve. Snowflake trials expire, so a clone of this repo would stop passing `make check` after the trial ends.

We want `make check` to be green on a fresh clone with no credentials, and we still want production to run on Snowflake.

## Decision

Commit `dbt/profiles.yml` with two targets and no secrets.

- `dev` uses dbt-duckdb with the database file `.dbt-local/oap.duckdb`. It is the default target, so `make dbt-compile` and CI need nothing beyond `uv sync --all-groups`.
- `prod` uses dbt-snowflake and reads every connection setting from environment variables: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`.

CI compiles on `dev`. Only `prod` runs models against Snowflake, and only from an operator's machine or a future scheduled job that holds the credentials.

## Consequences

- Models are compiled and built on DuckDB in `make check` and CI (`dbt build` seeds, runs and tests them). A passing check proves that Jinja renders, refs resolve, YAML is valid and the SQL and tests pass on DuckDB. It does not prove the SQL is valid on Snowflake.
- Adapter-specific SQL has to be avoided or dispatched. Prefer dbt's cross-database macros (`dbt.dateadd`, `dbt.datediff`, `dbt.safe_cast`) and `dbt_utils` over raw functions. Where a function differs, wrap it in a macro that uses `adapter.dispatch` with a `duckdb__` and a `snowflake__` implementation. Semi-structured data (`VARIANT`, `FLATTEN`), `TRY_TO_*` conversions and date-part functions are the likeliest places to diverge.
- Differences in type systems and case handling will show up in prod first. Snowflake upper-cases unquoted identifiers; DuckDB preserves case. Write lower-case snake_case and never quote identifiers.
- Phase 2 should add a `dbt build --target prod` run against the Snowflake trial before merging model changes, and record it in the runbook. Until then, a model change is only compile-checked.
- The DuckDB file is a local artefact. It is gitignored and safe to delete.

## Alternatives considered

**Mock the Snowflake adapter.** Rejected. A mock verifies only what we teach it, and it would drift from the real adapter. It adds code we would have to maintain for no gain over a real engine.

**Require a Snowflake trial for every contributor.** Rejected. It makes CI depend on stored secrets, makes forks unable to run checks, and ties the repo's health to a 30-day trial.

**Postgres as the local target.** Rejected. Postgres is further from Snowflake for analytical SQL than DuckDB is (no `QUALIFY`, weaker Parquet and semi-structured support), and it adds a service to run for a compile check. DuckDB is a single in-process file and can later read the bronze Parquet files directly for local experiments.
