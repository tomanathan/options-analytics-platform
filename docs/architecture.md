# Architecture

This document describes what is built. Phases 0 to 2 are done: ingestion into two bronze Iceberg tables, the quality gates, the Airflow DAGs that run them and the dbt silver and gold layers. Phase 3 is in progress: the engine's functions exist and are tested, and the backtest that runs them over gold is being added (see "Phase 3, in progress" below).

## Components

```mermaid
flowchart LR
    H[DoltHub options] -->|backfill_chains| A[Airflow]
    S[DoltHub stocks] -->|backfill_prices, daily_prices| A
    L[Alpaca snapshots] -->|daily_chain_snapshot| A
    A -->|PyIceberg, pool bronze_writers| B1[(bronze.option_chain)]
    A -->|PyIceberg, pool bronze_writers| B2[(bronze.underlying_price)]
    B1 & B2 -. Dataset update .-> D[dbt_build DAG]
    B1 & B2 -->|iceberg_scan, pinned| D
    D -->|dbt tests = gate 2| G[(DuckDB: silver, gold)]
    G --> E[Engine: src/oap/engine]
    GE[Great Expectations] -. gate 1 .- B1
```

| Component | Role | State |
| --- | --- | --- |
| DoltHub `options` | Historical chains from 2020 (free, no key). | `oap.ingest.dolthub`, used by `backfill_chains`. |
| DoltHub `stocks` | Daily as-traded OHLCV for the watchlist (free, no key). | `oap.ingest.dolthub_stocks`, used by `backfill_prices` and `daily_prices`. |
| Alpaca | Daily options snapshot, `indicative` feed. | `oap.ingest.alpaca`, used by `daily_chain_snapshot`. |
| Airflow 2.11.2 | Schedules ingest, the bronze gate, maintenance and the dbt build. LocalExecutor, Postgres metadata DB. | Seven DAGs, listed below. Image from `docker/airflow.Dockerfile`, installed from `uv.lock` (ADR 0006). |
| Iceberg catalog | Storage and catalog for the bronze tables. | Local by default: a stdlib-SQLite catalog (`oap.ingest.local_catalog`, ADR 0005) and a file warehouse in `.iceberg-local/`. S3 + Glue is selected by environment variables; Terraform defines the bucket, database and IAM user and is not applied by default. |
| dbt | Builds silver and gold from bronze. | Project `oap`, 10 models, 3 singular tests. Runs on DuckDB (`dev`), reading bronze through `iceberg_scan` (ADR 0008). |
| DuckDB | Local dbt target and the engine's input store. | `.dbt-local/oap.duckdb`; the synthetic build uses `.dbt-local/synthetic.duckdb`. |
| Snowflake | Production target for silver and gold. | A `prod` target in `profiles.yml`; not provisioned, and no model has run on it. |
| Great Expectations | Validates bronze. | `oap.quality.bronze_suite` runs after the daily chain write. The price table has the pandera write contract but no Great Expectations suite. |
| Spread engine | Pure functions that score put credit spreads. | `oap.engine`, built and tested (156 tests). |
| Redpanda | Intraday streaming. | Commented out in `docker-compose.yml`. |

## Bronze

Bronze holds the vendor response as received. Both tables are partitioned by `day(trade_date)` and `identity(source)`, and both are described by a `TableSpec` in `oap.ingest.tables` (`OPTION_CHAIN`, `UNDERLYING_PRICE`, collected in `BRONZE_TABLES`). The writer, reader, merge helper and maintenance DAG are generic over the spec, so a new bronze table is one more spec.

**`bronze.option_chain`** has one row per contract per day per source. Columns are `trade_date`, `underlying`, `occ_symbol` (compact OCC form such as `SPY240119C00470000`), `expiration`, `strike` (decimal(10,3)), `right`, `bid`, `ask`, `last`, `volume`, `open_interest`, `iv`, `delta`, `gamma`, `theta`, `vega`, `rho`, `underlying_price`, `source` and `ingested_at` (UTC). Eight are non-nullable: `trade_date`, `underlying`, `occ_symbol`, `expiration`, `strike`, `right`, `source` and `ingested_at`. The key is (occ_symbol, trade_date, source). Two sources write to it. DoltHub (`source=dolthub`) supplies history and has no last, volume, open interest or underlying price. Alpaca (`source=alpaca_indicative`) supplies the daily snapshot, whose quotes are derived from OPRA rather than the real NBBO, and has no open interest. Vendor IV and greeks are kept as received (ADR 0004). DoltHub's chains cover 2020-01-06 onward with roughly three sessions a week present; 1,476,854 rows were loaded before DIA and XLF were backfilled.

**`bronze.underlying_price`** has one daily bar per underlying per source: `trade_date`, `underlying`, `open`, `high`, `low`, `close`, `volume`, `source` (`dolthub_stocks`) and `ingested_at`. The key is (underlying, trade_date, source). Prices are dollars per share as traded, not adjusted for splits or dividends, because option strikes are quoted against the as-traded price (ADR 0007). `open` is not range-checked, as one vendor row has it above the high.

**The write rule.** Every write goes through `write_partition`, which replaces its (trade_date, source) slice with one overwrite commit and never appends, so re-runs, retries and overlapping backfills converge on the same table (ADR 0003). A slice holds every underlying of a day, so the backfills and the daily price DAG go through `merge_into_slices` (`oap.ingest.merge`): it replaces only the underlyings the vendor returned rows for, keeps the rest, and skips a slice whose content did not change. An empty response never deletes loaded rows.

**The watchlist** is the dbt seed `dbt/seeds/watchlist.csv`, read by the DAGs when `symbols` is empty. It has 11 symbols: SPY, DIA, XLF, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA and AMD. QQQ and IWM were dropped because DoltHub holds no options history for them.

**Serialising writers.** The SQLite catalog allows one writer. Every task that commits to bronze runs in the Airflow pool `bronze_writers`, which has one slot (created by `airflow-init`): the write tasks of `backfill_chains`, `daily_chain_snapshot`, `backfill_prices` and `daily_prices`, and both tasks of `iceberg_maintenance`. They queue behind each other instead of racing for the lock.

**Failing fast.** Retries exist for flaky networks. The decorator `fail_fast` (`dags/common.py`), applied under `@task`, turns errors a retry cannot fix into `AirflowFailException`: any `ValueError` (including `pyarrow.ArrowInvalid`), pandera `SchemaErrors`, `BronzeQualityError`, bad Alpaca credentials, an HTTP 4xx other than 429, and a snapshot for the wrong session. DoltHub and transport errors still retry. The `plan` tasks reject malformed symbols before any fetch.

## Pipelines

| DAG | Schedule | What it does | Pool | Emits Dataset |
| --- | --- | --- | --- | --- |
| `smoke` | Manual | Imports `oap` on a worker. | | |
| `backfill_chains` | Manual (`start`, `end`, `symbols`) | One fetch per (symbol, month), four at a time; one merge-and-write per month. | `bronze_writers` on `write_month` | `option_chain`, from `summarize` |
| `daily_chain_snapshot` | 16:30 America/New_York on NYSE sessions | `snapshot >> quality >> write`; the quality task runs the Great Expectations suite on the staged slice before anything is committed. | `bronze_writers` on `write` | `option_chain`, from `write` |
| `backfill_prices` | Manual (`start`, `end`, `symbols`) | One DoltHub query per month for all symbols; one merge-and-write per month. | `bronze_writers` on `write_month` | `underlying_price`, from `summarize` |
| `daily_prices` | 16:30 America/New_York on NYSE sessions | `fetch >> write` over a trailing window of five sessions; `write` skips when no slice changed. | `bronze_writers` on `write` | `underlying_price`, from `write` (not on a skipped run) |
| `iceberg_maintenance` | `@weekly` | Expires snapshots older than 7 days, then compacts multi-file slices, in both tables. | `bronze_writers` | |
| `dbt_build` | On either Dataset | `dbt_build >> publish_gold`: runs `dbt build` (or `dbt test`) over the pinned bronze snapshot; `publish_gold` skips unless the mode is `build`. | `duckdb_writer` on `dbt_build` | `gold`, from `publish_gold` |

The daily DAGs use `NYSECloseTimetable` (`dags/timetables.py`, registered by `plugins/oap_timetables.py`). Trading days come from `oap.calendar`.

DoltHub commits a session's bars at about 05:30 UTC on the next day. `daily_prices` therefore lags one session: the run for day D picks up D-1 and fills any gap in the five-session window, and D's own bar arrives with the run for D+1.

**Dataset scheduling.** `dags/datasets.py` defines two Datasets, `iceberg://oap/bronze/option_chain` and `iceberg://oap/bronze/underlying_price`. A producer task lists one in `outlets`, and Airflow records an update when that task succeeds. `dbt_build` is scheduled on `option_chain | underlying_price`, so either update starts a run, and `max_active_runs=1` makes a second run wait for the first. The URIs are identifiers; Airflow never reads them.

## Silver and gold

The dbt project reads bronze, builds the silver and gold schemas and tests them. Silver is `staging` plus `intermediate` (schema `silver`); gold is `marts` (schema `gold`). Bronze never passes through dbt models; it is a source.

**Reading bronze.** The `register_bronze` hook (`dbt/macros/register_bronze.sql`) reads each table's committed `metadata_location` from the SQLite catalog, pins that metadata version for the whole run, and creates the views `bronze.option_chain` and `bronze.underlying_price` over `iceberg_scan`. Models and tests therefore read one snapshot even while a backfill commits. `OAP_DBT_SOURCE` selects the catalog: `iceberg` (the real one), `synthetic` (written by `scripts/make_synthetic_bronze.py` through the real writer, used by `make check` and CI) or `auto`. A DuckDB file built from one mode refuses to build from the other. On Snowflake the hook does nothing and the sources point at `OAP_SNOWFLAKE_BRONZE_DATABASE` and `OAP_SNOWFLAKE_BRONZE_SCHEMA` (ADR 0008).

| Model | Layer | Materialisation | Grain |
| --- | --- | --- | --- |
| `stg_watchlist` | silver | view | symbol |
| `stg_option_chain` | silver | view | occ_symbol, trade_date, source |
| `stg_underlying_price` | silver | view | underlying, trade_date |
| `int_option_quotes` | silver | view | occ_symbol, trade_date |
| `int_chain_snapshots` | silver | table | underlying, trade_date, expiration |
| `dim_underlying` | gold | table | symbol |
| `dim_contract` | gold | table | occ_symbol |
| `fct_option_quote` | gold | incremental, delete+insert on trade_date | occ_symbol, trade_date |
| `fct_underlying_daily` | gold | table | underlying, trade_date |
| `fct_expiration_outcome` | gold | table | underlying, expiration |

`stg_option_chain` renames and filters: it drops rows with a non-positive strike, an expiration before the trade date or a crossed quote. `int_option_quotes` keeps one quote per contract per day (DoltHub wins over Alpaca when both cover a contract-day), adds `mid`, `spread`, `dte_days`, `dte_years` (calendar days over 365) and `moneyness`, and attaches `underlying_close`: the stocks close when a price row exists, the chain vendor's price otherwise, with `underlying_close_source` saying which. `fct_option_quote` is the engine's input. It is incremental on a watermark, the latest bronze `ingested_at` of each trade date, which mirrors the slice overwrites. `fct_underlying_daily` holds as-traded bars with simple and log returns; split days show as large moves and a warn-level test flags them. `fct_expiration_outcome` holds the settlement close of every expiration seen in the chains: the close on the expiration date, or on the last session within four days before it when the expiration falls on a holiday or weekend.

Every model has descriptions on every column and at least two tests, which `tests/dbt/test_project.py` enforces. A full build on 1.48 million option rows took about 12 seconds.

## The two gates

A gate decides whether the next layer may build, and fails closed.

**Gate 1, bronze: Great Expectations.** `oap.quality.bronze_suite` checks that `occ_symbol` has no nulls, `strike` is above zero, `right` is C or P, the key (occ_symbol, trade_date, source) is unique, and each underlying's row count is within 50% of the median of the trailing 20 sessions (underlyings with fewer than 5 days of history are not bounded). It runs in the `quality` task of `daily_chain_snapshot`, on what was written. A failure raises `BronzeQualityError`, fails the task and does not roll back the slice. The backfills do not run the suite; check them with `make iceberg-count`. Before every write, a pandera contract (`BRONZE_FRAME`, `PRICE_FRAME`) rejects malformed frames and commits nothing.

**Gate 2, silver to gold: dbt tests.** The tests run in `dbt build` in dependency order, and a test failing at error severity skips every model downstream of it and fails the `dbt_build` task. Beyond the column tests in the `schema.yml` files there are three singular tests:

- `assert_close_within_strike_range`: a day's close must lie inside the strike range of that day's chain. It catches a split-adjusted close set against as-traded strikes.
- `assert_fct_option_quote_matches_silver`: per trade date, gold must hold exactly the rows of the silver view. It catches drift the incremental watermark cannot see, such as a deleted bronze slice. The fix is a full refresh.
- `assert_synthetic_row_counts`: expected row counts of every model on the synthetic catalog. It exists only when `OAP_DBT_SOURCE=synthetic`.

## The engine

`src/oap/engine/` is a package of pure functions on numpy arrays: no I/O, no clock, no scipy. The units and conventions are fixed across it (ADR 0009): prices in dollars per share, volatility as a decimal, time in years on ACT/365, rates as decimal APY, probabilities as decimals. Invalid input raises `EngineInputError`.

| Module | What it provides |
| --- | --- |
| `conventions` | `dte_years` (ACT/365), `growth_factor`, `discount_factor`, `continuous_rate`. |
| `black_scholes` | Prices, delta, vega, no-arbitrage bounds, put-call parity forward and a vectorised bisection `implied_vol` that returns nan outside the bounds. |
| `implied_distribution` | `implied_cdf` builds a risk-neutral CDF of the price at expiry from vertical put spreads, with calls converted through parity. It repairs the raw slopes with weighted pool-adjacent-violators isotonic regression, clips to [0, 1], holds the CDF flat beyond the outer strikes, and reports what happened through `QualityFlag` (`NO_CALLS`, `FORWARD_UNKNOWN`, `MONOTONICITY_REPAIRED`, `CLIPPED`, `LEFT_TAIL_UNCOVERED`, `RIGHT_TAIL_UNCOVERED`, `SPARSE`, `CALIBRATED`). |
| `calibration` | Reliability table, Brier score, log loss, expected calibration error, an isotonic `CalibrationMap` (with `to_frame` and `from_frame`) and `apply_calibration`. |
| `spread_scoring` | `PutCreditSpread` and `SpreadScore`: probability of profit, probability of maximum loss, expected payoff, interest on the collateral at the cash APY, return on collateral, annualised return and Kelly fraction; `enumerate_spreads` and `rank_spreads`. |

156 tests cover the engine, including a property test that a lognormal chain is recovered. The engine does not read the warehouse. Reading gold and writing results is the job of code outside the package (see the next section). That keeps the math testable with `hypothesis` and lets a backtest replay any historical snapshot.

## Phase 3, in progress

The functions above are built. What is being added is the code around them: a backtest that replays the engine over `fct_option_quote` and checks its probabilities against `fct_expiration_outcome`, scoring of the current chains, and a report. Until that lands, nothing in the repository has run the engine over the loaded history, so no calibration result or return figure is claimed here.

## Local stack and cloud stack

| | Local | Cloud |
| --- | --- | --- |
| Orchestration | Airflow in Docker Compose, LocalExecutor, Postgres 16 | Not decided; the DAGs are portable to any Airflow 2.11 |
| Bronze | SQLite catalog and file warehouse in `.iceberg-local/` (`OAP_ICEBERG_CATALOG=sql`) | S3 bucket and Glue database from `infra/` (`OAP_ICEBERG_CATALOG=glue`) |
| dbt runner | `/opt/dbt-venv` in the Airflow image (the `dbt_build` DAG), `uv run dbt ...` on the host, or `docker compose run --rm dbt ...` | The same, with credentials in the environment |
| dbt target | `dev`: DuckDB file `.dbt-local/oap.duckdb`, with the iceberg, avro and sqlite extensions baked into the image at `/opt/duckdb-extensions` | `prod`: Snowflake, from `SNOWFLAKE_*` variables |
| dbt reads bronze | `iceberg_scan` over the local catalog, pinned per run | External Iceberg tables named by `OAP_SNOWFLAKE_BRONZE_DATABASE` and `_SCHEMA`; nothing in `infra/` creates them yet |
| Credentials | None for `make check` or the Airflow stack | AWS profile for Terraform and ingest; Snowflake user for `prod` |

The local stack is complete for development and CI, including the DoltHub chain history and the dbt build. Everything in the cloud column needs accounts the local stack does not: an AWS account for `terraform apply`, a Snowflake trial for `prod`. The daily Alpaca snapshot needs Alpaca keys in `.env` either way.

The Terraform IAM user is scoped to the one bucket and the one Glue database. Snowflake will need its own role, an external volume and external tables over the Glue tables; none exists (ADR 0001).
