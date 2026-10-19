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

Bronze is two Iceberg tables, both partitioned by `day(trade_date)` and `source`. Three feeds write to them.

| Source | Table and tag | Provides | Lacks |
| --- | --- | --- | --- |
| [DoltHub](https://www.dolthub.com/repositories/post-no-preference/options) `post-no-preference/options`. Free, no auth, SQL API. | `bronze.option_chain`, `dolthub` | History. Bid, ask, implied volatility, delta, gamma, theta, vega, rho. About 150 rows per symbol per day across 3 to 4 expirations. Coverage runs from 2020-01-06 to 2026-10-02 with roughly three sessions a week present; 1,476,854 rows were loaded before the DIA and XLF backfill. | Last price, volume, open interest and underlying price; stored as nulls. |
| [DoltHub](https://www.dolthub.com/repositories/post-no-preference/stocks) `post-no-preference/stocks`, table `ohlcv`. Same API. | `bronze.underlying_price`, `dolthub_stocks` | Daily open, high, low, close and volume for each watchlist symbol. | Split and dividend adjustment, by design (below). |
| Alpaca options snapshots, `feed=indicative`. Free tier, API key. | `bronze.option_chain`, `alpaca_indicative` | Daily snapshots after the NYSE close: bid, ask, last, volume, greeks, implied volatility, underlying price. | Open interest (null). Indicative quotes are derived from OPRA and are not the real NBBO, so spreads can be wider or narrower than a fill. |

The watchlist (`dbt/seeds/watchlist.csv`) has 11 symbols: SPY, DIA, XLF, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA and AMD. QQQ and IWM were replaced by DIA and XLF because DoltHub has no options history for them.

**Prices are as traded.** Closes are not adjusted for splits or dividends: AAPL closed at 499.23 on 2020-08-28 and 129.04 on 2020-08-31. That is the price option strikes are quoted against, which is what moneyness and expiration outcomes need. The `split` table is not applied, so `fct_underlying_daily` returns are wrong across split days (a warn-level test lists them) and the strike-range test `assert_close_within_strike_range` guards the unit ([ADR 0007](docs/decisions/0007-unadjusted-underlying-prices.md)).

**Price caveats.** DoltHub publishes session D at about 05:30 UTC on D+1, so `daily_prices` lags one session and re-fetches the last five. The `open` column is not range-checked, because the feed holds a row with an open above its high. Before 2022-06-09 the `META` ticker in this database is a different security (the Roundhill Metaverse ETF) and the FB history is not loaded; the loaded META chains start on 2022-07-01, so they never meet those rows, but META returns before the rename are not meaningful.

Both sources are for personal analysis only; their terms do not allow redistribution. For that reason no raw data is ever committed: the local Iceberg warehouse (`.iceberg-local/`) and `data/` are gitignored, and API keys live in `.env`, which is gitignored too. Vendor implied volatility and greeks are kept as received ([ADR 0004](docs/decisions/0004-keep-source-greeks.md)).

## Repo layout

| Path | Contents |
| --- | --- |
| `src/oap/` | The Python package. `calendar.py`: NYSE trading days and half days. `ingest/`: the DoltHub (`dolthub`, `dolthub_stocks`) and Alpaca clients, the bronze contracts (`schema`, `price_schema`), `tables` (one `TableSpec` per bronze table), the Iceberg writer, `merge` and the local catalog. `quality/`: the bronze Great Expectations suite. `engine/`: pure numpy functions for the spread engine: `conventions`, `black_scholes`, `implied_distribution`, `calibration`, `spread_scoring`. |
| `tests/` | pytest and hypothesis tests for the package, the DAGs, the scripts and the dbt project, in paths that mirror the code. The engine has 156, including a lognormal-recovery property test. |
| `dags/` | Airflow DAGs: `backfill_chains`, `daily_chain_snapshot`, `backfill_prices`, `daily_prices`, `iceberg_maintenance`, `dbt_build` and `smoke`. Shared code: `common.py` (defaults, the `bronze_writers` pool name, `fail_fast`), `datasets.py` (the two bronze Datasets that schedule `dbt_build`) and `timetables.py`. |
| `plugins/` | Airflow plugins. `oap_timetables.py` registers `NYSECloseTimetable`, which schedules the daily DAGs at 16:30 America/New_York on NYSE trading days only. |
| `dbt/` | dbt project `oap`. The watchlist seed; `models/staging` and `models/intermediate` (silver, mostly views); `models/marts` (gold: two dimensions and three facts, one incremental); `macros/register_bronze.sql`, which pins the Iceberg snapshot dbt reads; singular tests in `tests/`; and `profiles.yml` with a DuckDB `dev` and a Snowflake `prod` target. |
| `scripts/` | `iceberg_count.py` (`make iceberg-count`), `make_synthetic_bronze.py` (the catalog `make dbt-build` runs on) and `image_requirements.py` (picks the lock pins the Airflow image installs). |
| `infra/` | Terraform for the S3 bucket, Glue catalog database and a scoped IAM user. |
| `docker/` | `airflow.Dockerfile` (official Airflow image, dependencies installed from `uv.lock`, a separate dbt virtualenv; tagged `oap-airflow:dev`), the generated `requirements.txt` and `requirements-dbt.txt` it installs from (`make lock-export`), and the Dockerfile for the on-demand dbt container. |
| `docs/` | Architecture notes, the operator runbook and decision records. |
| `.github/workflows/` | CI: the `check` job (`make check`, then `pre-commit`) and the `infra` job (Terraform and Compose validation, and the dbt and Airflow image builds). |
| `.claude/` | Claude Code hooks, slash commands and agents for working in this repo. |

## Checks

`make check` runs the checks below and must pass before every commit. It needs no credentials and no vendor data. CI runs the same target (with the deterministic `ci` hypothesis profile) and then `pre-commit` over every file.

| Check | What it guards |
| --- | --- |
| `make lock-check` | `docker/requirements.txt` and `docker/requirements-dbt.txt` match `uv.lock`, so the Airflow image installs the versions CI tested. Fix: `make lock-export`. |
| `make lint` | `ruff` lint and format check: style drift and common bugs. |
| `make typecheck` | `mypy --strict` on `src/`, `tests/`, `dags/`, `plugins/` and `scripts/`: untyped or wrongly typed code, which matters most in the engine. |
| `make test` | `pytest`: package, DAG, script and dbt-project conventions, plus the `hypothesis` property tests of the engine. |
| `make dbt-compile` | `dbt compile` on DuckDB: Jinja, refs and YAML in every model. |
| `make dbt-build` | `make synthetic-bronze`, then `dbt build` twice on that synthetic Iceberg catalog (the second pass runs the incremental branch). It exercises the real bronze read path, every model and every test, including exact row counts. It does not prove the SQL on Snowflake (ADR 0002). |

Outside `make check`: `make dbt-build-local` builds silver and gold from the real local bronze tables into `.dbt-local/oap.duckdb` (stop `dbt_build` first; only one process may write that file). `make tf-fmt`, `make tf-validate` and `make compose-config` check the Terraform and Compose files and run in the CI `infra` job. `pre-commit` (install once with `uv run pre-commit install`) runs `detect-secrets`, ruff and file hygiene hooks on each commit.

## Roadmap

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Scaffolding: tooling, CI, Airflow stack, dbt skeleton, Terraform. | Done |
| 1 | Ingest DoltHub history, DoltHub daily prices and daily Alpaca snapshots into Iceberg bronze, with a quality gate. | Done. The chain history is loaded; the price loaders are built. |
| 2 | dbt silver and gold models with tests as the silver-to-gold gate, scheduled from the bronze Datasets. | Built on DuckDB. Snowflake is not provisioned and no model has run on it. |
| 3 | Spread engine: implied distribution, calibration against 2020+ outcomes, expected return on collateral. | In progress. The engine functions are built and tested; the backtest, scoring runs and report are being added. |

Intraday streaming (a Redpanda service is stubbed out, commented, in `docker-compose.yml`) comes after Phase 3.

## Why these choices

- [0001: Medallion layering with Iceberg bronze on S3](docs/decisions/0001-medallion-on-iceberg.md). Raw history stays replayable and schema-flexible outside the warehouse.
- [0002: DuckDB as the local and CI dbt target](docs/decisions/0002-duckdb-for-local-dbt.md). `make check` works on a fresh clone with no credentials.
- [0003: Overwrite the (trade_date, source) slice on every bronze write](docs/decisions/0003-partition-overwrite-for-idempotency.md). Backfills and re-runs are idempotent.
- [0004: Keep vendor implied volatility and greeks in bronze](docs/decisions/0004-keep-source-greeks.md). Bronze is as received, and the vendor values check our own model later.
- [0005: A standard-library SQLite catalog for local Iceberg](docs/decisions/0005-stdlib-sqlite-local-catalog.md). Airflow 2.11 and pyiceberg's `SqlCatalog` cannot share SQLAlchemy.
- [0006: Install the Airflow image's dependencies from the lock](docs/decisions/0006-image-dependencies-from-the-lock.md). The image runs the versions CI tested, without moving Airflow's own pins.
- [0007: Store underlying prices as traded](docs/decisions/0007-unadjusted-underlying-prices.md). Prices and option strikes are in the same unit on every date.
- [0008: dbt reads the Iceberg bronze tables through DuckDB](docs/decisions/0008-dbt-reads-iceberg-via-duckdb.md). Models and tests see one pinned snapshot, with no Snowflake account.
- [0009: Engine conventions](docs/decisions/0009-engine-conventions.md). APY rates, ACT/365 years and numpy only.

Architecture and data flow: [docs/architecture.md](docs/architecture.md). Operating the stack: [docs/runbook.md](docs/runbook.md). License: MIT.
