# options-analytics-platform

A data platform that turns free options-chain history into a ranked list of put credit spreads. Chains and daily prices land in Apache Iceberg tables, dbt builds silver and gold tables on DuckDB, and a walk-forward backtest checks the market-implied probabilities against what happened since 2020 before it scores the latest session's spreads. The project exists to build that path end to end, from vendor data to a ranked decision, with a quality gate between every layer.

```
DoltHub chains ─┐
DoltHub prices ─┼─> Airflow ─> Iceberg bronze ─> dbt silver, gold ─> analytics models ─> report
Alpaca daily ···┘   DAGs       option_chain      on DuckDB           calibration,        results.md
 (needs a key)                 underlying_price  (tests = gate 2)    spread scores       + figures
                                   └─ Great Expectations = gate 1 (daily chain snapshot)
Datasets chain the DAGs: bronze update -> dbt_build -> gold update -> score_spreads
```

**Status: Phases 0-3 are built and verified locally; the cloud targets are configured, not provisioned.** The local path (DuckDB, a file-based Iceberg catalog, Airflow in Docker Compose) runs end to end on the full DoltHub history. No Snowflake, AWS or Alpaca account exists yet, so Snowflake, S3 with Glue and the Alpaca snapshot are compile-checked or unit-tested configuration, and nothing has run on them.

## Quickstart

Needs Python 3.12, [uv](https://docs.astral.sh/uv/) and Docker (Colima works on macOS).

```bash
uv sync --all-groups                 # install dev, airflow, dbt and report dependency groups
make check                           # lock check, lint, mypy --strict, tests, dbt on synthetic data
cp .env.example .env                 # defaults work locally
make airflow-build && make up        # Airflow UI at http://localhost:8080 (airflow / airflow)
for d in backfill_prices dbt_build score_spreads; do docker compose exec -T airflow-scheduler airflow dags unpause $d; done
make backfill START=2020-01-01 END=2026-10-02    # chains: about an hour
docker compose exec -T airflow-scheduler airflow dags trigger backfill_prices \
  --conf '{"start": "2020-01-01", "end": "2026-10-02"}'    # prices: no make target
make report                          # after score_spreads finishes: docs/results.md and docs/img/
```

`dbt_build` and `score_spreads` start on Dataset updates, so there is nothing to trigger. `dbt_build` fails until both bronze tables exist and runs again on the next update. `make check` needs no credentials or data. The daily Alpaca snapshot needs `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in `.env`. Operating instructions are in [docs/runbook.md](docs/runbook.md).

## Results

<!-- results:start -->
Run `make report` to fill this section from the gold tables.
<!-- results:end -->

![Reliability diagram of out-of-sample probabilities, risk-neutral and calibrated](docs/img/calibration.png)

[docs/results.md](docs/results.md) has the coverage, exclusions, metrics by segment, the top spreads and the caveats. To read the reliability diagram, compare each series with the dashed diagonal: a point on it means events of that predicted probability happened that often. The calibrated series should lie closer to the diagonal than the risk-neutral one on out-of-sample years (2021 onward), and the lower panel shows how many predictions each bin holds.

## Highlights

- **Medallion on Iceberg.** Two bronze tables hold 1,811,734 option rows and 18,190 price rows for 11 underlyings over 1,194 trading days (2020-01-06 to 2026-10-02). Every write replaces its (trade_date, source) slice and skips unchanged content, so a re-run commits nothing and adds no snapshot.
- **dbt silver and gold.** 17 models (5 silver, 5 gold, 7 analytics) with 109 schema tests and 8 singular tests. Models read Iceberg through DuckDB with an `on-run-start` hook that pins one table version per run; an incremental gold fact is guarded by a row-count and checksum drift gate.
- **Pure numpy options engine.** Black-Scholes, vectorised implied volatility, a risk-neutral CDF from vertical spreads and spread scoring, with no scipy and units in every docstring. `hypothesis` property tests include recovering a known lognormal from synthetic chains.
- **Walk-forward calibration with leakage gates.** A yearly isotonic map is fitted only on expirations before 1 January of the year it scores; a singular test checks that in SQL. Metrics carry a cluster-bootstrap interval over expiration dates, and six exclusion rules count what they drop.
- **Airflow 2.11 orchestration.** Eight DAGs chained by Datasets (bronze, `dbt_build`, `score_spreads`), one-slot pools for the two single-writer stores, and fail-fast on errors a retry cannot fix. The daily gate runs before the write, so a failed gate publishes nothing. The full backfills ran through Airflow with no task failures on the final runs.
- **Lock-based image policy.** The Airflow image installs from `uv.lock` and a `pip check` gate; `make lock-check` fails when the exported requirements drift from the lock.
- **Quality bar.** 986 tests including the property tests, `mypy --strict`, `ruff`, `detect-secrets` in pre-commit, and CI jobs (`check`, `infra`) that are green on `main`; the `infra` job builds the Airflow image.

## Data

Bronze is two Iceberg tables, both partitioned by `day(trade_date)` and `source`. Three feeds write to them.

| Source | Table and tag | Provides | Lacks |
| --- | --- | --- | --- |
| [DoltHub](https://www.dolthub.com/repositories/post-no-preference/options) `post-no-preference/options`. Free, no auth, SQL API. | `bronze.option_chain`, `dolthub` | History. Bid, ask, implied volatility, delta, gamma, theta, vega, rho. About 150 rows per symbol per day across 3 to 4 expirations. Coverage runs from 2020-01-06 to 2026-10-02, with about 70% of sessions present. | Last price, volume, open interest and underlying price; stored as nulls. |
| [DoltHub](https://www.dolthub.com/repositories/post-no-preference/stocks) `post-no-preference/stocks`, table `ohlcv`. Same API. | `bronze.underlying_price`, `dolthub_stocks` | Daily open, high, low, close and volume for each watchlist symbol. | Split and dividend adjustment, by design (below). |
| Alpaca options snapshots, `feed=indicative`. Free tier, API key. | `bronze.option_chain`, `alpaca_indicative` | Daily snapshots after the NYSE close: bid, ask, last, volume, greeks, implied volatility, underlying price. Built and unit-tested; no key exists, so no snapshot has been taken. | Open interest (null). Indicative quotes are derived from OPRA and are not the real NBBO, so spreads can be wider or narrower than a fill. |

Loaded today: 1,811,734 chain rows over 1,194 trading days, and 18,190 price rows over 1,697 sessions (2020-01-02 to 2026-10-02). Chain days per underlying run from 822 (META, whose chains start in July 2022) to 1,191 (AAPL).

The watchlist (`dbt/seeds/watchlist.csv`) has 11 symbols: SPY, DIA, XLF, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA and AMD. QQQ and IWM were replaced by DIA and XLF because DoltHub has no options history for them.

**Prices are as traded.** Closes are not adjusted for splits or dividends: AAPL closed at 499.23 on 2020-08-28 and 129.04 on 2020-08-31. That is the price option strikes are quoted against, which is what moneyness and expiration outcomes need. The `split` table is not applied, so `fct_underlying_daily` returns are wrong across split days (a warn-level test lists them), the strike-range test `assert_close_within_strike_range` guards the unit, and the backtest excludes any snapshot whose window holds a move beyond 0.4 in log terms ([ADR 0007](docs/decisions/0007-unadjusted-underlying-prices.md)).

**Price caveats.** DoltHub publishes session D at about 05:30 UTC on D+1, so `daily_prices` lags one session and re-fetches the last five. The `open` column is not range-checked, because the feed holds a row with an open above its high. Before 2022-06-09 the `META` ticker in this database is a different security (the Roundhill Metaverse ETF) and the FB history is not loaded; the loaded META chains start on 2022-07-01, so they never meet those rows, and the backtest drops quotes before that date.

Both sources are for personal analysis only; their terms do not allow redistribution. For that reason no raw data is ever committed: the local Iceberg warehouse (`.iceberg-local/`), `.dbt-local/` and `data/` are gitignored, and API keys live in `.env`, which is gitignored too. Vendor implied volatility and greeks are kept as received ([ADR 0004](docs/decisions/0004-keep-source-greeks.md)).

## Repo layout

| Path | Contents |
| --- | --- |
| `src/oap/` | The Python package. `calendar.py`: NYSE trading days and half days. `ingest/`: the DoltHub (`dolthub`, `dolthub_stocks`) and Alpaca clients, the bronze contracts (`schema`, `price_schema`), `tables` (one `TableSpec` per bronze table), the Iceberg writer, `merge` and the local catalog. `quality/`: the bronze Great Expectations suite. `engine/`: pure numpy functions: `conventions`, `black_scholes`, `implied_distribution`, `calibration`, `spread_scoring`. `analytics/`: the calibration backtest and spread scoring over gold frames (`config`, `sample`, `backtest`, `scoring`, `io`), pure apart from `io`. |
| `tests/` | pytest and hypothesis tests for the package, the DAGs, the scripts and the dbt project, in paths that mirror the code. 986 in all. |
| `dags/` | Airflow DAGs: `backfill_chains`, `daily_chain_snapshot`, `backfill_prices`, `daily_prices`, `iceberg_maintenance`, `dbt_build`, `score_spreads` and `smoke`. Shared code: `common.py` (defaults, the `bronze_writers` pool name, `fail_fast`), `datasets.py` (bronze, `GOLD` and `GOLD_ANALYTICS` Datasets), `dbt_runner.py` (the dbt and report commands, the `duckdb_writer` pool name) and `timetables.py`. |
| `plugins/` | Airflow plugins. `oap_timetables.py` registers `NYSECloseTimetable`, which schedules the daily DAGs at 16:30 America/New_York on NYSE trading days only. |
| `dbt/` | dbt project `oap`. The watchlist seed; `models/staging` and `models/intermediate` (silver, views and one table); `models/marts` (gold: two dimensions and three facts, one incremental); `models/analytics` (seven Python models over `oap.analytics`, DuckDB only); `macros/register_bronze.sql`, which pins the Iceberg snapshot dbt reads; singular tests in `tests/`; and `profiles.yml` with a DuckDB `dev` and a Snowflake `prod` target. |
| `scripts/` | `iceberg_count.py` (`make iceberg-count`), `make_synthetic_bronze.py` (the catalog `make dbt-build` runs on), `make_report.py` (`make report`: results markdown, two figures and the README excerpt) and `image_requirements.py` (picks the lock pins the Airflow image installs). |
| `infra/` | Terraform for the S3 bucket, Glue catalog database and a scoped IAM user. Validated, never applied. |
| `docker/` | `airflow.Dockerfile` (official Airflow image, dependencies installed from `uv.lock`, a separate dbt virtualenv; tagged `oap-airflow:dev`), the generated `requirements.txt` and `requirements-dbt.txt` it installs from (`make lock-export`), and the Dockerfile for the on-demand dbt container. |
| `docs/` | Architecture notes, the operator runbook, decision records, and the generated `results.md` with `img/calibration.png` and `img/spread_scores.png` (written by `make report`). |
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
| `make dbt-build` | `make synthetic-bronze`, then `dbt build` on that synthetic Iceberg catalog in three passes: everything, the incremental model again, and the incremental model after two slices are rewritten the way a vendor correction rewrites them (a gold fact that missed the rewrite fails `assert_fct_option_quote_matches_silver`). It runs the real bronze read path, every model, including the analytics, and every test, then renders the report from the synthetic gold schema. It does not prove the SQL on Snowflake (ADR 0002). |

Outside `make check`: `make dbt-build-local` builds silver, gold and the analytics from the real local bronze tables into `.dbt-local/oap.duckdb`, and `make report` renders `docs/results.md` from that file (stop `dbt_build` and `score_spreads` first; only one process may write the file). `make tf-fmt`, `make tf-validate` and `make compose-config` check the Terraform and Compose files and run in the CI `infra` job. `pre-commit` (install once with `uv run pre-commit install`) runs `detect-secrets`, ruff and file hygiene hooks on each commit.

## Roadmap

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Scaffolding: tooling, CI, Airflow stack, dbt skeleton, Terraform. | Done |
| 1 | Ingest DoltHub history, DoltHub daily prices and daily Alpaca snapshots into Iceberg bronze, with a quality gate. | Done. Chains and prices are fully backfilled; the Alpaca snapshot waits for a key. |
| 2 | dbt silver and gold models with tests as the silver-to-gold gate, scheduled from the bronze Datasets. | Done on DuckDB. Snowflake is not provisioned and no model has run on it. |
| 3 | Spread engine: implied distribution, walk-forward calibration against 2020+ outcomes, expected return on collateral, report. | Done on DuckDB, as dbt Python models over `oap.analytics`, scheduled from the gold Dataset. |
| 4 | A per-date risk-free rate from FRED DTB3 in bronze, and the analytics models as Snowpark Python models. | Not started. The constant 4.5% APY and DuckDB-only models stay until then. |

Provisioning the cloud accounts (AWS for S3 and Glue, Snowflake, Alpaca) is not scheduled. Intraday streaming (a Redpanda service is stubbed out, commented, in `docker-compose.yml`) has no phase yet.

## Why these choices

- [0001: Medallion layering with Iceberg bronze on S3](docs/decisions/0001-medallion-on-iceberg.md). Raw history stays replayable and schema-flexible outside the warehouse.
- [0002: DuckDB as the local and CI dbt target](docs/decisions/0002-duckdb-for-local-dbt.md). `make check` works on a fresh clone with no credentials.
- [0003: Overwrite the (trade_date, source) slice on every bronze write](docs/decisions/0003-partition-overwrite-for-idempotency.md). Backfills and re-runs are idempotent; the daily gate runs before the write.
- [0004: Keep vendor implied volatility and greeks in bronze](docs/decisions/0004-keep-source-greeks.md). Bronze is as received, and the vendor values check our own model later.
- [0005: A standard-library SQLite catalog for local Iceberg](docs/decisions/0005-stdlib-sqlite-local-catalog.md). Airflow 2.11 and pyiceberg's `SqlCatalog` cannot share SQLAlchemy.
- [0006: Install the Airflow image's dependencies from the lock](docs/decisions/0006-image-dependencies-from-the-lock.md). The image runs the versions CI tested, without moving Airflow's own pins.
- [0007: Store underlying prices as traded](docs/decisions/0007-unadjusted-underlying-prices.md). Prices and option strikes are in the same unit on every date.
- [0008: dbt reads the Iceberg bronze tables through DuckDB](docs/decisions/0008-dbt-reads-iceberg-via-duckdb.md). Models and tests see one pinned snapshot, with no Snowflake account.
- [0009: Engine conventions](docs/decisions/0009-engine-conventions.md). APY rates, ACT/365 years and numpy only.
- [0010: Analytics as dbt Python models over a pure core](docs/decisions/0010-analytics-as-dbt-python-models.md). One writer for DuckDB, walk-forward calibration, moneyness-grid sampling.

Architecture and data flow: [docs/architecture.md](docs/architecture.md). Operating the stack: [docs/runbook.md](docs/runbook.md). License: MIT.
