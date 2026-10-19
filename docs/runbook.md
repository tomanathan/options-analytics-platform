# Runbook

For whoever operates the stack. All commands run from the repo root unless noted. "Operating" means the Airflow stack, the bronze pipelines (chain and price backfills, the daily DAGs, maintenance), the dbt build, Terraform and the checks.

## Airflow stack

Services: `postgres` (metadata DB), `airflow-init` (one-shot migrate and create user), `airflow-webserver`, `airflow-scheduler`. LocalExecutor. `make up`, `make down`, `make reset` and `make logs` wrap the commands below; `make down` keeps the metadata volume, `make reset` deletes it.

The containers receive `AWS_REGION`, the Iceberg and Glue settings (`OAP_ICEBERG_*`, `OAP_S3_BUCKET`, `OAP_GLUE_DATABASE`) and `ALPACA_*` from `.env`. The `dbt_build` DAG sets its own dbt environment (catalog, DuckDB file and extension paths inside the container), so the `OAP_DBT_*` variables in `.env` affect only host runs and the on-demand `dbt` service. By default the DAGs write to the local Iceberg catalog; see "Local and AWS catalog" below for switching to S3 and Glue. `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are passed through from the shell that runs `docker compose`, not from `.env`.

Start:

```bash
cp .env.example .env            # first time only
docker compose up -d
curl -s http://localhost:8080/health
```

The UI is at http://localhost:8080. The login is `_AIRFLOW_WWW_USER_USERNAME` / `_AIRFLOW_WWW_USER_PASSWORD` from `.env` (default `airflow` / `airflow`). `/health` should report `healthy` for both `metadatabase` and `scheduler`; the scheduler entry can take a minute after startup. To check the whole path, trigger the smoke DAG, which imports `oap` on the worker:

```bash
docker compose exec airflow-scheduler airflow dags unpause smoke
docker compose exec airflow-scheduler airflow dags trigger smoke
```

Status and logs:

```bash
docker compose ps
docker compose logs -f airflow-scheduler
docker compose logs --tail=100 airflow-webserver
docker compose logs airflow-init
```

Stop, keeping the metadata database:

```bash
docker compose down
```

Reset to a clean slate. `-v` deletes the Postgres volume, so connections, variables and run history are lost:

```bash
docker compose down -v
docker compose up -d
```

Re-run `airflow-init` if the database migration failed or the admin user was not created. It is safe to repeat, but it does not change the password of an existing user:

```bash
docker compose up airflow-init
```

To change an existing user's password:

```bash
docker compose exec airflow-webserver airflow users reset-password --username airflow
```

Run an Airflow CLI command inside the stack:

```bash
docker compose exec airflow-scheduler airflow dags list
```

## Bronze pipelines

Six DAGs write, maintain or build on the two bronze tables, `bronze.option_chain` and `bronze.underlying_price`:

| DAG | Trigger | Writes |
| --- | --- | --- |
| `backfill_chains` | By hand: `make backfill` | `option_chain`, DoltHub history |
| `daily_chain_snapshot` | 16:30 New York on NYSE sessions | `option_chain`, Alpaca snapshot |
| `backfill_prices` | By hand: `airflow dags trigger` | `underlying_price`, DoltHub daily bars |
| `daily_prices` | 16:30 New York on NYSE sessions | `underlying_price`, trailing five sessions |
| `iceberg_maintenance` | Weekly | Both tables: expire snapshots, compact |
| `dbt_build` | On a bronze Dataset update | Nothing in bronze; see "dbt" below |

The table design and the overwrite rule are in [architecture.md](architecture.md) and [ADR 0003](decisions/0003-partition-overwrite-for-idempotency.md). Locally the tables live in `.iceberg-local/` (gitignored); inside the containers that directory is mounted at `/opt/airflow/.iceberg-local`. The local catalog is a standard-library SQLite file, `.iceberg-local/catalog.db` ([ADR 0005](decisions/0005-stdlib-sqlite-local-catalog.md)); it supports one writer host, so do not point two machines at one file. Iceberg metadata records container-absolute file paths. pyiceberg therefore works only inside the containers (`make iceberg-count`), while DuckDB reads the same files from the host, which is how `make dbt-build-local` works ([ADR 0008](decisions/0008-dbt-reads-iceberg-via-duckdb.md)).

The watchlist is `dbt/seeds/watchlist.csv`: SPY, DIA, XLF, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA and AMD. QQQ and IWM were replaced by DIA and XLF because DoltHub has no options history for them; a backfill for QQQ or IWM produces skipped fetches only.

### Build the Airflow image

All Airflow services share one image, `oap-airflow:dev`, built from `docker/airflow.Dockerfile`. It installs `oap`'s dependencies at the versions in `uv.lock` ([ADR 0006](decisions/0006-image-dependencies-from-the-lock.md)). After any change to dependencies in `pyproject.toml`:

```bash
uv lock
make lock-export      # rewrites docker/requirements.txt and docker/requirements-dbt.txt
make airflow-build
make up               # recreates the containers on the new image
```

Python edits under `src/`, `dags/`, `plugins/` and `scripts/` need no rebuild, because those directories are mounted. `make up` builds the image only if it does not exist yet. `make lock-check` (part of `make check`) fails when the two requirements files disagree with `uv.lock`; the fix is `make lock-export` and committing both files.

**Precedence rule.** The image starts from the official Airflow image, whose packages sit at Airflow's constraint versions. `oap`'s direct dependencies (the `dependencies` list in `pyproject.toml`) and every package the base image lacks are installed at the lock's versions with `--no-deps`. Any other package the base image already has keeps Airflow's version, and Airflow and dbt packages are never taken from the lock. To force one more package to the lock's version, add `--prefer-lock <name>` to the `image_requirements.py` call in the Dockerfile.

**The `pip check` gate.** The build runs `pip check` and fails on any finding except two, which are in packages nothing here imports: `awswrangler` wants `pyarrow<23` and `sagemaker-studio` wants `numpy<2.3`. If the build stops on another line, that line names the conflict. Either the package should come from the lock (add `--prefer-lock`) or the dependency change is not compatible with Airflow 2.11 and has to be reverted. Do not add a third exception without amending ADR 0006.

dbt runs from its own virtualenv, `/opt/dbt-venv`, built from `docker/requirements-dbt.txt`. dbt packages and the DuckDB extensions (iceberg, avro, sqlite) are baked into the image, so a DAG run needs no network. Check what the image holds:

```bash
docker compose exec -T airflow-scheduler python -c "import numpy, pandas, pyarrow, pyiceberg; print(numpy.__version__, pandas.__version__, pyarrow.__version__, pyiceberg.__version__)"
docker compose exec -T airflow-scheduler /opt/dbt-venv/bin/dbt --version
```

If a DAG fails with `ModuleNotFoundError` for a third-party package, the image is stale: run `make airflow-build`, then `make up`.

### The `bronze_writers` pool

The SQLite catalog allows one writer, so every task that commits to a bronze table runs in the Airflow pool `bronze_writers`, which has one slot. `airflow-init` creates it on every start (`airflow pools set` is an upsert). The tasks in it are `write_month` of both backfills, `write` of both daily DAGs, and both tasks of `iceberg_maintenance`. They run one at a time, in the order the scheduler queues them.

```bash
docker compose exec -T airflow-scheduler airflow pools get bronze_writers
```

In the UI, Admin, then Pools shows how many slots are running and queued. A write task in `queued` while another write runs is normal: for example, the 16:30 daily write waits behind a long backfill month. Do not raise the slot count; two simultaneous commits fight over the SQLite write lock.

If a write task never leaves `scheduled` and the scheduler log says it uses a non-existent pool, the pool is missing. Recreate it:

```bash
docker compose exec -T airflow-scheduler airflow pools set bronze_writers 1 "One commit at a time to the bronze Iceberg tables"
```

### What is not retried

`DEFAULT_ARGS` gives every task two retries, five minutes apart, and the DoltHub fetch tasks get five with exponential backoff up to ten minutes. Retries help with a flaky network. They do not help when the same input fails the same way, so tasks decorated with `fail_fast` (`dags/common.py`) turn deterministic errors into `AirflowFailException`, which fails the task at once:

- any `ValueError`, which includes `pyarrow.ArrowInvalid` and the symbol check in `plan`;
- a pandera `SchemaErrors`, raised when a frame breaks the bronze contract before a write;
- `BronzeQualityError`, raised by the Great Expectations gate;
- Alpaca errors that are not transient: bad or missing credentials, an HTTP 4xx other than 429, and a snapshot whose session is not the run's.

DoltHub errors, timeouts, HTTP 429 and 5xx still retry. When a task fails fast, the first line of its log reads `AirflowFailException: <ErrorType>: <message>`. Fix the cause, then clear the task (UI grid, or `airflow tasks clear`). Retrying it first would only repeat the error.

`dbt_build` is not wrapped in `fail_fast`. It retries once after two minutes, so a failing dbt test fails twice with the same result.

### Run a backfill for one month

```bash
make backfill START=2024-01-01 END=2024-01-31
make backfill START=2024-01-01 END=2024-03-31 SYMBOLS=SPY,DIA
```

`SYMBOLS` defaults to the watchlist seed (mounted read-only into the containers). The make target unpauses the DAG and triggers it with the dates as run parameters. The equivalent direct commands:

```bash
docker compose exec -T airflow-scheduler airflow dags unpause backfill_chains
docker compose exec -T airflow-scheduler airflow dags trigger backfill_chains \
  --conf '{"start": "2024-01-01", "end": "2024-01-31", "symbols": ["SPY", "DIA"]}'
```

An empty `symbols` list means the watchlist. The DAG plans one fetch task per (symbol, month) with at least one NYSE session in range, runs at most 4 tasks at once, and retries each fetch up to 5 times with exponential backoff (capped at 10 minutes). A fetch that finds no rows in DoltHub ends as `skipped`, not failed, and leaves whatever that symbol already has in the table untouched: absence in a response is never treated as a deletion (ADR 0003). DoltHub's chains cover 2020-01-06 onward, with roughly three sessions a week present, so a range before 2020 produces skipped fetches only. After the fetches, one write task per month merges the staged symbols into each day's slice and overwrites it, one month at a time. A write is skipped for any slice whose content did not change, so repeating a backfill adds no snapshots. Only one backfill run is active at a time; a second trigger waits.

To add a symbol to the watchlist, add a row to `dbt/seeds/watchlist.csv`, then backfill that symbol only, for example `make backfill START=2020-01-01 END=<yesterday as YYYY-MM-DD> SYMBOLS=DIA,XLF`, and the same symbols for prices (next section).

DoltHub notes: range predicates on `date` time out, so the client queries each month with an explicit list of trading days and pages with `LIMIT 1000 OFFSET n`. With an explicit `LIMIT`, DoltHub reports a full page as `Success` rather than `RowLimit`, so the client keeps paging while a page holds exactly 1000 rows. Timeouts, HTTP 429 and 5xx responses are retried inside the client before Airflow's own retries begin. Rows with a crossed quote (bid above ask) are dropped with a logged `WARNING` giving the count per underlying and date.

### Prices: backfill and daily refresh

`bronze.underlying_price` holds the DoltHub `stocks.ohlcv` bars: open, high, low, close in dollars per share and volume in shares, source `dolthub_stocks`. The closes are as traded, not split-adjusted ([ADR 0007](decisions/0007-unadjusted-underlying-prices.md)): AAPL is 499.23 on 2020-08-28 and 129.04 on 2020-08-31. That is correct. The dbt build reads this table, so it must exist and cover the chain dates before `dbt_build` can succeed.

Backfill. `end` has no default and `start` defaults to 2020-01-01. There is no make target; use the Airflow CLI:

```bash
docker compose exec -T airflow-scheduler airflow dags unpause backfill_prices
docker compose exec -T airflow-scheduler airflow dags trigger backfill_prices \
  --conf '{"start": "2020-01-01", "end": "2026-10-16"}'
```

Add `"symbols": ["DIA", "XLF"]` to limit it. The DAG runs one DoltHub query per month for all symbols (four months at a time), then one merge-and-write per month in the `bronze_writers` pool. It is safe to repeat: unchanged slices are skipped.

The refresh. `daily_prices` runs at 16:30 New York on NYSE sessions. DoltHub publishes session D at about 05:30 UTC on D+1, so at 16:30 on D its own bar is not there. Each run fetches the last five sessions up to its own, so it picks up D-1 and fills small gaps, and D's bar arrives with the next run. The latest session in the table is therefore normally one session behind. An empty response for the whole window fails the task on purpose, because five sessions without a single bar means the feed is stale.

Verify what landed. `make iceberg-count` reads `bronze.option_chain` only, so use this for prices:

```bash
docker compose exec -T airflow-scheduler python - <<'PY'
from oap.ingest.iceberg_writer import catalog_from_env, table_identifier
from oap.ingest.tables import UNDERLYING_PRICE

table = catalog_from_env().load_table(table_identifier(spec=UNDERLYING_PRICE))
frame = table.scan(selected_fields=("trade_date", "underlying")).to_arrow().to_pandas()
print(frame.groupby("underlying")["trade_date"].agg(["count", "min", "max"]).to_string())
print("total", len(frame), "rows,", frame["trade_date"].nunique(), "dates")
PY
```

Expect one line per watchlist symbol, the same `max` date for all of them (normally the last completed session before today, because of the publication lag), and counts that match across symbols that existed for the whole range. A symbol whose `max` is behind the others is missing a bar that DoltHub did not publish; re-run `backfill_prices` for that month later. The command fails with `NoSuchTableError` if no price has been written yet.

Two data facts to keep in mind. DoltHub's `open` is not range-checked; the feed holds a row (IWM on 2021-05-05, found while probing it; IWM is not on the watchlist) with an open above its high, and the parser logs a warning and keeps such rows. And before 2022-06-09 the `META` ticker in this database is a different security (the Roundhill Metaverse ETF), with no FB history loaded.

### Re-run a failed day

Run the backfill for that single date:

```bash
make backfill START=2024-01-17 END=2024-01-17 SYMBOLS=SPY
```

For prices, trigger `backfill_prices` with the same date as `start` and `end`. Both are safe to repeat. Each write replaces the (trade_date, source) slice and never appends, so the re-run produces the same rows as a clean run and leaves no duplicates (ADR 0003). Other symbols already in the slice are kept. `ingested_at` differs when a slice is rewritten; `make iceberg-count ARGS="--hash"` prints content hashes that exclude it. If a month's write task fails with "fetch failed for ..." or "<month>: fetch failed", one of its fetches did not finish; its slices were left untouched, so re-run that month.

A failed `daily_chain_snapshot` task is retried by clearing it in the UI grid or with `airflow tasks clear`. Alpaca returns the latest snapshot, so a run triggered long after its session fails on purpose with a wrong-session error rather than store the quotes of the trigger time under that session's date. Re-run an Alpaca session the same evening or not at all. To fill a missed past day, use the DoltHub backfill, with its column limits (no last, volume, open interest or underlying price).

### Watch progress

```bash
docker compose exec -T airflow-scheduler airflow dags list-runs -d backfill_chains
docker compose exec -T airflow-scheduler airflow tasks states-for-dag-run backfill_chains <run_id>
```

Get `<run_id>` from `list-runs`; use `backfill_prices` in place of `backfill_chains` for prices. `states-for-dag-run` prints one line per task instance and map index; count the states of `fetch_month` to see how many tasks are `success`, `running`, `up_for_retry`, `skipped` or `failed`, and those of `write_month` for the months. In the UI (http://localhost:8080), open the DAG, then Grid: each mapped task shows a count badge, and clicking it lists each map index with its logs. Logs are also on disk under `logs/airflow/`. The `summarize` task logs the totals.

### Count what landed

```bash
make iceberg-count
make iceberg-count ARGS="--source dolthub --start 2024-01-01 --end 2024-01-31"
make iceberg-count ARGS="--summary"
make iceberg-count ARGS="--hash"
```

This runs `scripts/iceberg_count.py` in the scheduler container against `bronze.option_chain`. It streams three columns (`trade_date`, `source`, `underlying`) in Arrow batches, so memory stays flat however large the table is. The default output has one line per (source, trade_date) with its row count, then one line per (source, underlying) with days, rows and the first and last date, then the total. Flags:

| Flag | Effect |
| --- | --- |
| `--start`, `--end` | Restrict to a trade-date range, inclusive. |
| `--source dolthub` or `alpaca_indicative` | Restrict to one feed. |
| `--summary` | Leave out the per-slice lines. |
| `--hash` | Add a `content_hash` to each slice line and, at the end, a `content_digest` over all selected slices. Each slice is read on its own, so the full table takes about 80 seconds. |

Run `--hash` before and after a re-run: an unchanged `content_digest` shows the re-run was a no-op. `ingested_at` is excluded from the hash. The digest replaces the single whole-table `content_hash` line that older versions printed, and the two are not comparable. The script exits with an error if the table does not exist yet (nothing has been written). Prices have no equivalent script; use the snippet in the previous section.

### Quality failures

The `quality` task of `daily_chain_snapshot` reads the written slice back and runs the bronze suite (`src/oap/quality/bronze_suite.py`) against the previous 20 sessions of the same source. A failed expectation raises `BronzeQualityError`, naming the failed expectations, and fails the task without a retry. The backfill DAGs do not run the suite; check their output with `make iceberg-count`. A failure does not roll back the write: the slice stays as written until it is re-run. Frames are also validated against the bronze contract before every write (for chains: bid not above ask, expiration not before trade date, unique key, strike above zero, right in C/P; for prices: close above zero, volume not negative, high not below low, close inside the range, unique key); a violation fails the write task with the list of failed checks and commits nothing. The price table has no Great Expectations suite.

**`row_count:<SYMBOL>`.** The underlying's row count for the day is outside the band: within 50% of the median over its previous 20 sessions. Underlyings with fewer than 5 days of history are not bounded.
- Below the band: usually a vendor outage or a partial response. Re-run the day (the same evening for Alpaca). If it stays low, check the vendor directly.
- Above the band: new expirations were listed, or the same data was written under two source tags. Inspect the slice with `make iceberg-count` before re-running.

**`occ_symbol_not_null`.** The parser failed to build the compact OCC symbol for some rows. This is a bug in `src/oap/ingest/`, not a data problem. Do not re-run until the parser is fixed, because the re-run overwrites with the same bad rows.

**`strike_positive` or `right_in_set`.** Malformed vendor rows or a column mapping error. Read the failing expectation in the task log. If the vendor changed a format, fix the mapping, then re-run.

**`key_unique`.** Duplicates on (occ_symbol, trade_date, source). The overwrite rule should make this impossible within one source tag. It means two writers used the same `source` value, or the vendor sent the same contract twice. Check the `source` column of the slice; if a writer is tagging with the wrong source, fix it and re-run both days.

### Maintenance DAG

`iceberg_maintenance` runs weekly. For each bronze table it expires snapshots older than 7 days, always keeping the current one, then compacts: any (trade_date, source) slice with more than one data file is read and written back through the same overwrite path, because pyiceberg 0.12 has no `rewrite_data_files`; the rows, including `ingested_at`, are unchanged. Run it by hand:

```bash
docker compose exec -T airflow-scheduler airflow dags unpause iceberg_maintenance
docker compose exec -T airflow-scheduler airflow dags trigger iceberg_maintenance
```

Run it after a large backfill: retries and re-runs leave replaced data files referenced by old snapshots until they expire. Expiring snapshots limits time travel to 7 days. In pyiceberg 0.12 expiry removes snapshot metadata only; superseded data files stay on disk until a later phase adds an orphan-file sweep.

### Local and AWS catalog

The catalog is chosen by environment variables (set them in `.env`; Compose passes them to the containers):

| Variable | Local (default) | AWS |
| --- | --- | --- |
| `OAP_ICEBERG_CATALOG` | `sql` (alias `local`) | `glue` |
| `OAP_ICEBERG_URI` | `sqlite:///.iceberg-local/catalog.db` | not used |
| `OAP_ICEBERG_WAREHOUSE` | `file://./.iceberg-local/warehouse` | `s3://<bucket>/bronze` |
| `OAP_GLUE_DATABASE` | not used | `oap_bronze` (the tables' namespace) |

In AWS mode the tables are `<OAP_GLUE_DATABASE>.option_chain` and `<OAP_GLUE_DATABASE>.underlying_price`. The containers cannot read `~/.aws` profiles, so export `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` for the `oap-pipeline` user in the shell that runs `docker compose`, together with `AWS_REGION`. Switching also needs the Terraform resources applied. The local and AWS tables are separate; nothing copies one to the other. The dbt hook reads only the local SQLite catalog; building from Glue is not implemented.

### Full history backfill

Chains, run overnight:

```bash
make backfill START=2020-01-01 END=<yesterday as YYYY-MM-DD>
```

For 11 symbols over about 81 months that is roughly 900 fetch tasks at 4 concurrent, about one hour when DoltHub answers quickly. DoltHub rate limits can stretch it. The run is resumable: if tasks fail after their retries, re-run the same command; unchanged slices are skipped and the overwrite rule makes the repeat safe. Then prices, with the trigger command in the price section above. Finish with `make iceberg-count`, the price verification snippet and the maintenance DAG.

### Schema changes

If `ensure_table` raises `ValueError` about a column type after a schema change (Iceberg cannot change a decimal's scale in place), the stored table does not match the code. As a last resort, stop the stack, delete `.iceberg-local/`, start it and re-run the backfills. Nothing in that directory is a source of truth: both tables are rebuilt from DoltHub (chains and prices), though the Alpaca snapshots taken so far cannot be fetched again. After the rebuild, trigger `dbt_build` with `{"full_refresh": true}`; the incremental gold table compares bronze write times and a rebuilt table has new ones, but the drift test will tell you if anything was missed.

## dbt

The dbt project `oap` builds the `silver` and `gold` schemas from the two bronze tables ([architecture.md](architecture.md) lists the models). It runs in three places, all on the DuckDB `dev` target and all reading bronze through the `register_bronze` hook ([ADR 0008](decisions/0008-dbt-reads-iceberg-via-duckdb.md)): the `dbt_build` DAG in the Airflow container, `make dbt-build-local` on the host, and `make check` on synthetic data. No Snowflake run has been done; `prod` is a target in `profiles.yml` only, and the models have only been compiled and built on DuckDB.

### The `dbt_build` DAG

`dbt_build` runs `/opt/dbt-venv/bin/dbt` in a single bash task, `dbt_build`, against `.dbt-local/oap.duckdb` and the catalog in `.iceberg-local/`. It has no cron schedule: it runs when either bronze Dataset is updated (next section). Unpause it once; a paused DAG does not run.

```bash
docker compose exec -T airflow-scheduler airflow dags unpause dbt_build
docker compose exec -T airflow-scheduler airflow dags trigger dbt_build
docker compose exec -T airflow-scheduler airflow dags trigger dbt_build --conf '{"mode": "test"}'
docker compose exec -T airflow-scheduler airflow dags trigger dbt_build --conf '{"full_refresh": true}'
```

| Param | Values | Effect |
| --- | --- | --- |
| `mode` | `build` (default), `test` | `build` runs models and tests in dependency order. `test` runs only the tests against the tables already in `oap.duckdb`. |
| `full_refresh` | `false` (default), `true` | Rebuilds the incremental `fct_option_quote` from scratch. Applies to `mode=build` only. |

Use `{"mode": "test"}` to re-check after fixing bronze without rebuilding. Use `{"full_refresh": true}` after anything the incremental watermark cannot see: a bronze slice deleted by writing an empty frame, a rebuilt `.iceberg-local/`, or a failure of `assert_fct_option_quote_matches_silver`.

A dbt test that fails at error severity skips every model downstream of it and fails the task. This is the silver-to-gold gate; Great Expectations remains the bronze gate. Warn-level tests are reported and do not fail the run.

**Artifacts.** dbt writes its target and logs inside the container, in `/tmp/dbt-target/<run_id>`, because the project directory is mounted read-only. Whether the build passes or fails, `manifest.json` and `run_results.json` are copied to `.dbt-local/artifacts/` on the host, overwriting the previous run's. List everything that did not pass:

```bash
python3 - <<'PY'
import json

for r in json.load(open(".dbt-local/artifacts/run_results.json"))["results"]:
    if r["status"] not in ("success", "pass"):
        print(r["status"], r["unique_id"], r["message"])
PY
```

The statuses are `error`, `fail`, `warn` and `skipped`. The full dbt output is in the task log (UI, task `dbt_build`, Logs) and on disk under `logs/airflow/dag_id=dbt_build/`.

**One writer.** Only one process may write `oap.duckdb` at a time. `max_active_runs=1` keeps `dbt_build` from overlapping itself, but nothing stops you from starting a second writer by hand. Do not run `make dbt-build-local`, `docker compose run --rm dbt build` or any read-write DuckDB session on the file while a `dbt_build` run is active. A collision shows as `Could not set lock on file ... Conflicting lock is held`. Check what is running, then wait or stop the other process:

```bash
docker compose exec -T airflow-scheduler airflow dags list-runs -d dbt_build --state running
```

To look at the data without blocking anything, copy the file and open the copy read-only:

```bash
cp .dbt-local/oap.duckdb /tmp/oap-inspect.duckdb
uv run python -c "import duckdb; print(duckdb.connect('/tmp/oap-inspect.duckdb', read_only=True).sql('select count(*) from gold.fct_option_quote'))"
```

### Why `dbt_build` ran: Dataset scheduling

`dags/datasets.py` defines `iceberg://oap/bronze/option_chain` and `iceberg://oap/bronze/underlying_price`. A task that succeeds with one in its `outlets` records a Dataset update. These tasks are `backfill_chains.summarize`, `daily_chain_snapshot.quality`, `backfill_prices.summarize` and `daily_prices.write`. `dbt_build` is scheduled on either Dataset, so any one of them starts a run, and a second update during a run queues a following run (`max_active_runs=1`). The daily chain snapshot and the daily price refresh both run at 16:30, so on an evening when both succeed expect up to two `dbt_build` runs.

To see why a run exists:

```bash
docker compose exec -T airflow-scheduler airflow dags list-runs -d dbt_build
```

A run started by a Dataset has the type `dataset_triggered`; one you started has `manual`. For a Dataset run, list the events that triggered it. The run id contains `+`, which must be written `%2B` in the URL; the login is the Airflow UI login:

```bash
curl -s -u airflow:airflow \
  "http://localhost:8080/api/v1/dags/dbt_build/dagRuns/<run_id>/upstreamDatasetEvents"
```

Each event names the `dataset_uri` and the `source_dag_id`, `source_task_id` and `source_run_id` that produced it. The Datasets page of the UI shows the same events and the producer and consumer DAGs.

A manual trigger does not need a Dataset. A bronze commit made outside Airflow (for example a script) records no Dataset event, so run `dbt_build` by hand afterwards.

### Build on the host

```bash
make dbt-build-local
```

This runs `dbt deps`, then `dbt build` on the real local catalog (`OAP_DBT_SOURCE=iceberg`, `OAP_ICEBERG_LOCAL_DIR=.iceberg-local`) into `.dbt-local/oap.duckdb`, the same file the DAG writes. It needs both bronze tables to exist, and the first run downloads the DuckDB iceberg, avro and sqlite extensions into `~/.duckdb/extensions`, so it needs network once. Stop `dbt_build` first (see "One writer"). A full build with tests took about 12 seconds on 1.48 million option rows.

### Build on synthetic data

`make check` needs no vendor data. `make synthetic-bronze` writes a small deterministic bronze catalog to `.dbt-local/synthetic-iceberg` through the real writer: three underlyings, 13 sessions in January 2024, 1,380 chain rows and 38 price rows. `make dbt-build` then runs `dbt build` on it twice (the second pass exercises the incremental branch) into its own file, `.dbt-local/synthetic.duckdb`, which it deletes first. `assert_synthetic_row_counts` checks the row count of every model and exists only in this mode.

`oap.duckdb` and `synthetic.duckdb` are never mixed. A DuckDB file records the mode it was built from in `bronze.registered_snapshot`, and a run in the other mode stops in the `on-run-start` hook:

```text
Compilation Error in operation oap-on-run-start-0 (./dbt_project.yml)
  this DuckDB file was built from synthetic bronze, this run reads iceberg; set another OAP_DUCKDB_PATH or delete the file
```

Fix: you pointed a run at the wrong file or mode. Check `OAP_DBT_SOURCE` and `OAP_DUCKDB_PATH`; if the file is the wrong one to keep, delete it (`rm .dbt-local/oap.duckdb`) and rebuild. Everything in it is rebuilt from bronze. `OAP_DBT_SOURCE=auto` (the default outside the Make targets and the DAG) reads the real catalog if `.iceberg-local/catalog.db` exists and the synthetic one otherwise, so an unset variable can pick the other mode on a machine where the real catalog appears or disappears; set it explicitly.

### dbt failures

Find the failing test in `run_results.json` (above) or the task log. The first two rows are hook errors, raised before any model runs.

| Failure | Likely cause | Fix |
| --- | --- | --- |
| `bronze.underlying_price is not in .../catalog.db` (or `bronze.option_chain`) | That table has never been written, so it is not in the catalog. The first chain commit starts `dbt_build` before any price exists. | Run `backfill_prices` (or the missing table's backfill), then trigger `dbt_build`. |
| `this DuckDB file was built from X bronze, this run reads Y` | Mode lock; see "Build on synthetic data". | Delete the file or set `OAP_DUCKDB_PATH`. |
| `assert_close_within_strike_range` | On some day, an underlying's close lies outside the strike range of its own chain. Usually the price rows hold split-adjusted values, or a ticker stands for another instrument. | List the days (query below). Re-run `backfill_prices` for those months; if a price row is wrong at the vendor, there is nothing to fix here, and the test should not be loosened. |
| `assert_fct_option_quote_matches_silver` | Gold holds different rows from silver for some trade date: a bronze slice was deleted or rewritten without a newer `ingested_at`, so the incremental watermark skipped it. | Trigger `dbt_build` with `{"full_refresh": true}`. |
| `unique_combination_of_columns` on `stg_option_chain` | Duplicate (occ_symbol, trade_date, source) in bronze. The Great Expectations `key_unique` check should have caught it. | Treat as `key_unique` above, then re-run the day. |
| `unique_combination_of_columns` on `stg_underlying_price` | A second price source landed. The test deliberately excludes `source` so it fails closed. | A rule for choosing between sources has to be written first; see the model's docs block. |
| `relationships` of `underlying` to `stg_watchlist` on `stg_option_chain` | Bronze holds an underlying that is not in `dbt/seeds/watchlist.csv`. | Add the symbol to the seed (the build reloads it) or stop ingesting it. On `stg_underlying_price` this test is warn-only. |
| `accepted_values` on `source` | A new source tag reached bronze. | Add it to the model's `schema.yml` after deciding how it ranks against the others in `int_option_quotes`; write an ADR if it is a new vendor. |
| `not_null_proportion` on `underlying_close` (`int_option_quotes`, at least 0.99) | Over 1% of quote rows have no close: prices are missing for the range, or the latest sessions are inside the one-session publication lag. | Run `backfill_prices` for the range, or wait for the next `daily_prices` run. The plain `not_null` on the column is warn-only. |
| `expect_column_values_to_be_between` on `spread_pct` (0 to 2), `moneyness` (above 0), `mid` (not below 0), `dte_days` (not below 0) | A vendor row with a nonsensical quote or date. | Read the failing rows in the test output; fix the vendor mapping if it is systematic, otherwise treat as a data defect and keep the gate. |
| `settlement_lag_days` between 0 and 4 (`fct_expiration_outcome`) | An expiration settled on a session more than 4 days before it: a hole in the price history. | Run `backfill_prices` for the months around that expiration. |
| `log_return` between -0.5 and 0.5 (`fct_underlying_daily`), warn | A split day (expected: AAPL 2020-08-31, for example) or the `META` series crossing 2022-06-09, where the ETF becomes Meta. | None; the warning lists them. Returns are not split-adjusted. |
| `assert_synthetic_row_counts` | The synthetic data or a model's logic changed. Synthetic mode only. | If the change is intended, update the expected counts in the test and in the docstring of `scripts/make_synthetic_bronze.py`. |

To list the rows behind `assert_close_within_strike_range`, copy the DuckDB file (see "One writer") and run:

```sql
select underlying, trade_date, max(underlying_close) as underlying_close,
       min(min_strike) as min_strike, max(max_strike) as max_strike
from silver.int_chain_snapshots
group by underlying, trade_date
having max(underlying_close) < min(min_strike) or max(underlying_close) > max(max_strike)
order by trade_date, underlying
```

Silver and gold are rebuildable at any time from bronze, so a bad dbt build is never a data-loss event: delete `.dbt-local/oap.duckdb` and run `dbt_build` again.

### dbt without Airflow

Other dbt commands use the same project and profile directory:

```bash
make dbt-deps        # install dbt_utils and dbt_expectations
make dbt-compile     # compile on the synthetic catalog, no data needed
```

`dbt compile` skips the bronze hook, so it needs no catalog. In the on-demand container (the `dbt` service is under the `tools` profile, so `docker compose up` does not start it), the project, `.dbt-local` and the Iceberg directory are mounted:

```bash
mkdir -p .dbt-local
docker compose run --rm dbt deps
docker compose run --rm dbt compile
```

That container is a plain `python:3.12-slim` with pinned dbt versions and has no baked-in DuckDB extensions; a build in it downloads them.

Against Snowflake (`prod`), set the `SNOWFLAKE_*` variables in `.env`. The sources then read `OAP_SNOWFLAKE_BRONZE_DATABASE` and `OAP_SNOWFLAKE_BRONZE_SCHEMA`, which must hold tables named `option_chain` and `underlying_price`. Nothing in `infra/` creates them, so this path has not been run.

```bash
docker compose run --rm dbt build --target prod
```

Or run it from the host, exporting `.env` first:

```bash
set -a; source .env; set +a
uv run dbt build --project-dir dbt --profiles-dir dbt --target prod
```

## Terraform

Terraform needs an AWS account and a named profile. Create the profile once with `aws configure --profile oap-admin`, using an administrator or a role allowed to create S3, Glue and IAM resources. This is separate from the `oap-pipeline` profile the ingest code uses (see `.env.example`), so day-to-day runs never carry admin rights.

```bash
export AWS_PROFILE=oap-admin
terraform -chdir=infra init
terraform -chdir=infra plan -var bucket_name=<globally-unique-bucket-name>
terraform -chdir=infra apply -var bucket_name=<globally-unique-bucket-name>
```

`bucket_name` has no default because S3 names are global. To avoid retyping it, copy the example and edit it (`cp infra/terraform.tfvars.example infra/terraform.tfvars`; the copy is gitignored), then drop the `-var` flags. The same name goes in `OAP_S3_BUCKET` in `.env`. After apply, `terraform -chdir=infra output` prints the bucket, the Glue database and the IAM user. State is local (`infra/terraform.tfstate`, gitignored); do not delete it while resources exist.

Check formatting and validity without credentials or an account: `make tf-fmt` and `make tf-validate`.

Destroy, only when you want the resources gone. The bucket is versioned, so it must be emptied of all versions first:

```bash
terraform -chdir=infra destroy -var bucket_name=<name>
```

### Rotate the IAM access key

Terraform creates the IAM user (`oap-pipeline`) but no access key, so keys live outside state. Rotation creates the new key before removing the old one:

```bash
export AWS_PROFILE=oap-admin  # the administrator profile, not the key being rotated
USER_NAME=$(terraform -chdir=infra output -raw pipeline_user_name)
aws iam list-access-keys --user-name "$USER_NAME"
aws iam create-access-key --user-name "$USER_NAME"
```

Store the new key in the `oap-pipeline` profile (`aws configure --profile oap-pipeline`) or the secret store the ingest code uses. Confirm it works, then delete the old one:

```bash
aws iam update-access-key --user-name "$USER_NAME" --access-key-id <old-key-id> --status Inactive
aws iam delete-access-key --user-name "$USER_NAME" --access-key-id <old-key-id>
```

Deactivate first, wait a day, then delete, so a forgotten consumer fails loudly and can be fixed. A user can hold at most two keys.

## Running the checks

```bash
uv sync --all-groups
make check          # lock-check, lint, typecheck, test, dbt-compile, dbt-build on synthetic data
make lock-check     # docker/requirements*.txt match uv.lock (also part of make check)
make dbt-build      # dbt build twice on the synthetic bronze catalog
make tf-fmt         # needs terraform on PATH
make tf-validate
make compose-config # needs docker on PATH
uv run pre-commit install   # once per clone: runs the hooks on every commit
```

`make format` rewrites files with ruff. `make clean` removes caches, build output, `.dbt-local` (the DuckDB files, synthetic catalog and dbt artifacts, all rebuildable) and `.venv`, so the next `make install` starts from scratch. It does not touch `.iceberg-local/`. `make check` includes `lock-check`, so a dependency change without `make lock-export` fails it. It needs no vendor data and no credentials; the dbt build in it reads the synthetic catalog, never `.iceberg-local/`.

## Common failures

**Port 8080 already in use.** `docker compose up` fails with "port is already allocated". Find the holder with `lsof -i :8080`, stop it, or change the host side of the webserver port mapping in `docker-compose.yml` (for example `8081:8080`).

**Cannot connect to the Docker daemon (macOS).** Colima is not running. Start it with `colima start`, confirm with `docker ps`, and retry. If Colima is up but compose is slow, give it more memory: `colima stop && colima start --memory 6`. Airflow with Postgres needs about 4 GB.

**Webserver is up but the scheduler is unhealthy.** Check `docker compose logs airflow-scheduler`. The usual cause is `airflow-init` not having completed; run `docker compose up airflow-init` and read its output.

**A DAG does not appear, or shows "Broken DAG".** Import errors show as a red banner at the top of the UI. The same list is available from the CLI:

```bash
docker compose exec airflow-scheduler airflow dags list-import-errors
```

The scheduler log (`docker compose logs airflow-scheduler`) holds the traceback. A frequent cause is importing `oap` when `PYTHONPATH` does not include `/opt/airflow/src`; check `docker compose exec airflow-scheduler env | grep PYTHONPATH`. Reproduce it without the stack with `uv run pytest tests/dags -q`, which loads every DAG file into a DagBag.

**Permission denied on `logs/airflow` on Linux.** Set `AIRFLOW_UID` in `.env` to the output of `id -u`, create the directory yourself with `mkdir -p logs/airflow`, then `docker compose down -v && docker compose up -d`.

**`ModuleNotFoundError` in a DAG task, or the `backfill_chains` DAG is missing.** The image predates a dependency change. Run `make airflow-build` and `make up`, then `docker compose exec airflow-scheduler airflow dags list-import-errors`.

**`make airflow-build` fails in the `pip check` step.** The output lists the conflicting requirement. Only the `awswrangler`/pyarrow and `sagemaker-studio`/numpy findings are allowed (see "Build the Airflow image"). Anything else means a dependency change collides with a package Airflow ships.

**`make lock-check` says a requirements file is out of date.** Run `make lock-export` and commit `docker/requirements.txt` and `docker/requirements-dbt.txt` with the `uv.lock` change.

**A bronze write task stays `scheduled`.** The `bronze_writers` pool is missing; see "The `bronze_writers` pool".

**`dbt_build` fails before any model runs.** The `register_bronze` hook could not find a bronze table or the DuckDB file was built in the other mode; both are in "dbt failures".

**`dbt` cannot lock `oap.duckdb`.** Another process holds the file; see "One writer".

**`dbt compile` cannot find packages.** Run `make dbt-deps`. Packages install to `dbt/dbt_packages/`, which is gitignored. In the Airflow image they are baked in at `/opt/dbt-packages/dbt_packages`.

**`dbt` on `prod` fails to connect.** One of the `SNOWFLAKE_*` variables is empty or unexported. Check with `env | grep SNOWFLAKE_ | sed 's/=.*/=.../'` so the password is not printed.

**`detect-secrets` blocks a commit.** Read the reported file and line. If it is a real secret, remove it and rotate it. If it is a false positive, run `uv run detect-secrets scan --baseline .secrets.baseline`, review the diff, and commit the updated baseline.
