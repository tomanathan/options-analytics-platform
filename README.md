# options-analytics-platform

A data platform for scoring put credit spreads, built in phases. Options chains land in Apache Iceberg tables, will be modeled with dbt on Snowflake, and will feed a spread engine. The engine will extract the market-implied probability distribution from vertical spread prices, calibrate it against realized outcomes since 2020 (where the free history starts), and score every candidate spread on expected return on collateral, including interest on the cash held against it (a configurable APY; Robinhood Gold pays 3.6% today). The project exists to build that path end to end, from vendor data to a ranked decision, with a quality gate between every layer. **Today it is Phase 1: ingestion and bronze are built; the history backfill has not been run yet.**

```
DoltHub (history) ─┐
                   ├─> Airflow ──> Iceberg bronze ──> dbt on Snowflake ──> spread engine
Alpaca (daily)  ───┘   DAGs        bronze.option_chain  silver ──> gold     src/oap/engine
                                         │                 │          │
                                         └─ Great Expectations gates ─┘
```

Phase 2 and 3 (dbt layers, gates beyond bronze, the engine) are drawn as the target; only the left half exists.

**Status: Phase 1, built; history backfill pending.** On top of the Phase 0 tooling, CI, Airflow stack, dbt skeleton and Terraform, the repo now has two ingest clients (DoltHub and Alpaca), an Iceberg writer for `bronze.option_chain`, a Great Expectations bronze gate, and three DAGs: `backfill_chains`, `daily_chain_snapshot` and `iceberg_maintenance`. Every write replaces its (trade_date, source) slice, so re-runs are safe ([ADR 0003](docs/decisions/0003-partition-overwrite-for-idempotency.md)). The engine and the dbt layers above bronze do not exist yet; Phase 2 and 3 will add them.

## Quickstart

Needs Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker (Colima works on macOS).

```bash
uv sync --all-groups          # install dev, airflow and dbt dependency groups
make check                    # lint, typecheck, test, dbt compile
cp .env.example .env          # local settings; defaults work for Airflow
make airflow-build            # build the Airflow image with oap installed
make up                       # Airflow UI at http://localhost:8080 (airflow / airflow)
make backfill START=2024-01-01 END=2024-03-31 SYMBOLS=SPY,QQQ   # one quarter, two symbols
make iceberg-count            # rows per (trade_date, source) in the local table
```

`make check` needs no credentials: dbt compiles against a local DuckDB file. The DoltHub backfill needs no key either; the daily Alpaca snapshot needs `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in `.env`. Operating instructions, including the full-history backfill, are in [docs/runbook.md](docs/runbook.md).

## Data

Bronze is one Iceberg table, `bronze.option_chain`, partitioned by `day(trade_date)` and `source`, one row per contract per day per source. Two sources feed it:

| Source | Role | Provides | Lacks |
| --- | --- | --- | --- |
| [DoltHub](https://www.dolthub.com/repositories/post-no-preference/options) `post-no-preference/options` | History. Free, no auth, SQL API. Tag `dolthub`. | Bid, ask, implied volatility, delta, gamma, theta, vega, rho. About 150 rows per symbol per day across 3 to 4 expirations. Coverage for the watchlist starts in 2020, with scattered missing trading days. | Last price, volume, open interest and underlying price; stored as nulls. |
| Alpaca options snapshots, `feed=indicative` | Daily snapshots after the NYSE close. Free tier, API key. Tag `alpaca_indicative`. | Bid, ask, last, volume, greeks, implied volatility, underlying price. | Open interest (null). Indicative quotes are derived from OPRA and are not the real NBBO, so spreads can be wider or narrower than a fill. |

Both sources are for personal analysis only; their terms do not allow redistribution. For that reason no raw data is ever committed: the local Iceberg warehouse (`.iceberg-local/`) and `data/` are gitignored, and API keys live in `.env`, which is gitignored too. Vendor implied volatility and greeks are kept as received ([ADR 0004](docs/decisions/0004-keep-source-greeks.md)).

## Repo layout

| Path | Contents |
| --- | --- |
| `src/oap/` | The Python package: `calendar.py` (NYSE trading days and half days), `ingest/` (DoltHub and Alpaca clients, bronze schema, Iceberg writer, local catalog), `quality/` (the bronze Great Expectations suite), `engine/` (pure pricing and scoring functions; documented stubs until Phase 3). |
| `tests/` | pytest tests for the package, the DAGs and the dbt project, in paths that mirror the code. |
| `dags/` | Airflow DAGs, their shared defaults and the timetable class, mounted into the containers: `backfill_chains`, `daily_chain_snapshot`, `iceberg_maintenance` and a `smoke` DAG. |
| `plugins/` | Airflow plugins. `oap_timetables.py` registers `NYSECloseTimetable` (defined in `dags/timetables.py`), which schedules the daily DAG at 16:30 America/New_York on NYSE trading days only. |
| `dbt/` | dbt project `oap`: seeds, staging and mart models, and a `profiles.yml` with a DuckDB `dev` and a Snowflake `prod` target. |
| `infra/` | Terraform for the S3 bucket, Glue catalog database and a scoped IAM user. |
| `docker/` | `airflow.Dockerfile` (official Airflow image plus `pip install .`, tagged `oap-airflow:dev`; rebuild with `make airflow-build`) and the Dockerfile for the on-demand dbt container. |
| `scripts/` | `iceberg_count.py`, run by `make iceberg-count`. |
| `docs/` | Architecture notes, the operator runbook and decision records. |
| `.github/workflows/` | CI: the `check` job (`make check`) and the `infra` job (Terraform and Compose validation, and the dbt and Airflow image builds). |
| `.claude/` | Claude Code hooks, slash commands and agents for working in this repo. |

## Checks

`make check` runs the checks below and must pass before every commit. CI runs the same target (with the deterministic `ci` hypothesis profile) and then `pre-commit` over every file.

| Check | What it guards |
| --- | --- |
| `make lint` | `ruff` lint and format check: style drift and common bugs. |
| `make typecheck` | `mypy --strict` on `src/`, `tests/` and `dags/`: untyped or wrongly typed code, which matters most in the engine. |
| `make test` | `pytest`: package, DAG and dbt-project conventions. `hypothesis` profiles are registered for the property tests the engine will need. |
| `make dbt-compile` | `dbt compile` on DuckDB: Jinja, refs and YAML in every model. |
| `make dbt-build` | `dbt build` on DuckDB: seeds, runs and tests every model locally. It does not prove the SQL on Snowflake (see ADR 0002). |

`make tf-fmt`, `make tf-validate` and `make compose-config` check the Terraform and Compose files and run in the CI `infra` job. `pre-commit` (install once with `uv run pre-commit install`) runs `detect-secrets`, ruff and file hygiene hooks on each commit.

## Roadmap

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Scaffolding: tooling, CI, Airflow stack, dbt skeleton, Terraform. | Done |
| 1 | Ingest DoltHub history and daily Alpaca snapshots into Iceberg bronze, with a quality gate. | Built; history backfill pending |
| 2 | dbt silver and gold models on Snowflake, with Great Expectations gates between layers. | Planned |
| 3 | Spread engine: implied distribution, calibration against 2020+ outcomes, expected return on collateral. | Planned |

Intraday streaming (a Redpanda service is stubbed out, commented, in `docker-compose.yml`) comes after Phase 3.

## Why these choices

- [0001: Medallion layering with Iceberg bronze on S3](docs/decisions/0001-medallion-on-iceberg.md). Raw history stays replayable and schema-flexible outside the warehouse.
- [0002: DuckDB as the local and CI dbt target](docs/decisions/0002-duckdb-for-local-dbt.md). `make check` works on a fresh clone with no credentials.

- [0003: Overwrite the (trade_date, source) slice on every bronze write](docs/decisions/0003-partition-overwrite-for-idempotency.md). Backfills and re-runs are idempotent.
- [0004: Keep vendor implied volatility and greeks in bronze](docs/decisions/0004-keep-source-greeks.md). Bronze is as received, and the vendor values check our own model later.
- [0005: A standard-library SQLite catalog for local Iceberg](docs/decisions/0005-stdlib-sqlite-local-catalog.md). Airflow 2.11 and pyiceberg's `SqlCatalog` cannot share SQLAlchemy.

Architecture and data flow: [docs/architecture.md](docs/architecture.md). License: MIT.
