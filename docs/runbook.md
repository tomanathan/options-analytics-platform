# Runbook

For whoever operates the stack. All commands run from the repo root unless noted. "Operating" means the Airflow stack, the bronze pipelines (chain and price backfills, the daily DAGs, maintenance), the dbt build, the analytics and the results report, the explorer, the nightly cloud refresh, Terraform and the checks.

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

Seven DAGs write, maintain or build on the two bronze tables, `bronze.option_chain` and `bronze.underlying_price` (the `smoke` DAG only imports `oap`):

| DAG | Trigger | Writes |
| --- | --- | --- |
| `backfill_chains` | By hand: `make backfill` | `option_chain`, DoltHub history |
| `daily_chain_snapshot` | 16:30 New York on NYSE sessions | `option_chain`, Alpaca snapshot |
| `backfill_prices` | By hand: `airflow dags trigger` | `underlying_price`, DoltHub daily bars |
| `daily_prices` | 16:30 New York on NYSE sessions | `underlying_price`, trailing five sessions |
| `iceberg_maintenance` | Weekly | Both tables: expire snapshots, compact |
| `dbt_build` | On a bronze Dataset update | Nothing in bronze; see "dbt" below |
| `score_spreads` | On the `gold` Dataset, after `dbt_build` | Nothing in bronze; see "Analytics and the report" below |

Every DAG starts paused. Unpause the ones you want to run: `for d in backfill_prices dbt_build score_spreads; do docker compose exec -T airflow-scheduler airflow dags unpause $d; done` (`make backfill` unpauses `backfill_chains` itself).

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

### Pools

Two Airflow pools, each with one slot, stand in for locks on the two single-writer stores. `airflow-init` creates both on every start (`airflow pools set` is an upsert).

| Pool | Protects | Tasks in it |
| --- | --- | --- |
| `bronze_writers` | The SQLite Iceberg catalog, one commit at a time. | `write_month` of both backfills, `write` of both daily DAGs, both tasks of `iceberg_maintenance`. |
| `duckdb_writer` | `.dbt-local/oap.duckdb`, one process at a time. | `dbt_build` of `dbt_build`; `analytics` and `report` of `score_spreads`. |

```bash
docker compose exec -T airflow-scheduler airflow pools list
docker compose exec -T airflow-scheduler airflow pools get duckdb_writer
```

A task of either DAG waiting in `queued` while another holds the pool is normal: a `score_spreads` run waits for a `dbt_build` run to end, and the reverse. Do not raise either slot count. A pool does not stop a process outside Airflow, so `make dbt-build-local` and `make report` are not covered (see "One writer"). If a task never leaves `scheduled` and the scheduler log names a missing pool, recreate it:

```bash
docker compose exec -T airflow-scheduler airflow pools set duckdb_writer 1 "One process at a time on .dbt-local/oap.duckdb"
```

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
- Vendor errors that are not transient: bad or missing Alpaca credentials, an HTTP 4xx other than 429, a non-JSON body or unexpected response shape, a DoltHub SQL error, and an Alpaca snapshot whose session is not the run's.

Transport errors, timeouts, HTTP 429 and 5xx still retry: a `DoltHubError` or `AlpacaError` raised after the client's own retries ran out carries the retryable cause and uses the task's retries. When a task fails fast, the first line of its log reads `AirflowFailException: <ErrorType>: <message>`. Fix the cause, then clear the task (UI grid, or `airflow tasks clear`). Retrying it first would only repeat the error.

`dbt_build` is not wrapped in `fail_fast`. It retries once after two minutes, so a failing dbt test fails twice with the same result. The `analytics` task of `score_spreads` has `retries=0`, because a failed leakage or monotonicity gate fails the same way again.

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

On a day when nothing changed, `write` raises `AirflowSkipException` and ends `skipped`, not `success`. That is normal, for example when the next bar has not been published yet or the run repeats the previous window. A skipped task emits no Dataset event, so `daily_prices` then does not start `dbt_build`. To see which case it was, read the task log: it says how many slices were unchanged.

```bash
docker compose exec -T airflow-scheduler airflow tasks states-for-dag-run daily_prices <run_id>
```

A `skipped` write is a problem only when the latest session in the table is more than one session behind. Check with the verification snippet below, then re-run `backfill_prices` for the gap.

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

The `quality` task of `daily_chain_snapshot` runs the bronze suite (`src/oap/quality/bronze_suite.py`) on the staged frame, before anything is committed, against the previous 20 sessions of the same source. A failed expectation raises `BronzeQualityError`, naming the failed expectations, and fails the task without a retry. The `write` task then does not run, so nothing was published: the slice of that session is exactly as it was before the run, and no Dataset event fired, so `dbt_build` did not start. After a good write, `write` reads the slice back and fails if its row count differs from the staged frame. The backfill DAGs do not run the suite; check their output with `make iceberg-count`. To repeat a gated run, fix the cause and clear the failed task (the same evening for Alpaca; see "Re-run a failed day"). Frames are also validated against the bronze contract before every write (for chains: bid not above ask, expiration not before trade date, unique key, strike above zero, right in C/P; for prices: close above zero, volume not negative, high not below low, close inside the range, unique key); a violation fails the write task with the list of failed checks and commits nothing. The price table has no Great Expectations suite.

**`row_count:<SYMBOL>`.** The underlying's row count for the day is outside the band: within 50% of the median over its previous 20 sessions. Underlyings with fewer than 5 days of history are not bounded.
- Below the band: usually a vendor outage or a partial response. Re-run the day (the same evening for Alpaca). If it stays low, check the vendor directly.
- Above the band: new expirations were listed, or the same data was written under two source tags. Compare the session's neighbours with `make iceberg-count` before re-running; the gated slice itself was not written.

**`occ_symbol_not_null`.** The parser failed to build the compact OCC symbol for some rows. This is a bug in `src/oap/ingest/`, not a data problem. Do not re-run until the parser is fixed, because the re-run stages the same bad rows and fails the gate again.

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

For 11 symbols over about 81 months that is roughly 900 fetch tasks at 4 concurrent, about one hour when DoltHub answers quickly. DoltHub rate limits can stretch it. The run is resumable: if tasks fail after their retries, re-run the same command; unchanged slices are skipped and the overwrite rule makes the repeat safe. Then prices, with the trigger command in the price section above. Finish with `make iceberg-count`, the price verification snippet and the maintenance DAG. The load of 2026-10-02 holds 1,811,734 chain rows over 1,194 trading days and 18,190 price rows over 1,697 sessions (2020-01-02 to 2026-10-02); the chain total is a check on a rebuild, and a later total is higher only because DoltHub published more sessions.

### Schema changes

If `ensure_table` raises `ValueError` about a column type after a schema change (Iceberg cannot change a decimal's scale in place), the stored table does not match the code. As a last resort, stop the stack, delete `.iceberg-local/`, start it and re-run the backfills. Nothing in that directory is a source of truth: both tables are rebuilt from DoltHub (chains and prices), though the Alpaca snapshots taken so far cannot be fetched again. After the rebuild, trigger `dbt_build` with `{"full_refresh": true}`; the incremental gold table compares bronze write times and a rebuilt table has new ones, but the drift test will tell you if anything was missed.

## dbt

The dbt project `oap` builds the `silver` and `gold` schemas from the two bronze tables, and the analytics models in `gold` on top of them ([architecture.md](architecture.md) lists the models). It runs in three places, all on the DuckDB `dev` target and all reading bronze through the `register_bronze` hook ([ADR 0008](decisions/0008-dbt-reads-iceberg-via-duckdb.md)): the `dbt_build` DAG in the Airflow container, `make dbt-build-local` on the host, and `make check` on synthetic data. No Snowflake run has been done; `prod` is a target in `profiles.yml` only, and the models have only been compiled and built on DuckDB.

### The `dbt_build` DAG

`dbt_build` runs `/opt/dbt-venv/bin/dbt` in a bash task, `dbt_build`, against `.dbt-local/oap.duckdb` and the catalog in `.iceberg-local/`, in the `duckdb_writer` pool. It excludes the models tagged `analytics`; `score_spreads` builds those. A second task, `publish_gold`, updates the `GOLD` Dataset after a `build` run whose models and tests passed, and raises `AirflowSkipException` after a `test` run, so `mode=test` does not trigger the analytics. A `skipped` `publish_gold` on a `mode=test` run is correct. On a `build` run it means something is wrong: check `params.mode` in the run's conf. It has no cron schedule: it runs when either bronze Dataset is updated (next section). Unpause it once; a paused DAG does not run.

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

**One writer.** Only one process may write `oap.duckdb` at a time. `max_active_runs=1` and the `duckdb_writer` pool keep `dbt_build` and `score_spreads` from overlapping, but nothing stops you from starting a second writer by hand. Do not run `make dbt-build-local`, `make report`, `docker compose run --rm dbt build` or any read-write DuckDB session on the file while a `dbt_build` or `score_spreads` run is active. A collision shows as `Could not set lock on file ... Conflicting lock is held`. Check what is running, then wait or stop the other process:

```bash
docker compose exec -T airflow-scheduler airflow dags list-runs -d dbt_build --state running
docker compose exec -T airflow-scheduler airflow dags list-runs -d score_spreads --state running
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

The same mechanism links `dbt_build` to `score_spreads`: `publish_gold` lists `duckdb://oap/gold` in `outlets`, and `score_spreads` is scheduled on it. Its runs are `dataset_triggered` too, and the events call `publish_gold` their source task. A skipped `publish_gold` emits no event, which is how a failed silver or gold test, or a `mode=test` run, keeps the analytics from starting.

### Analytics and the report

`score_spreads` has two tasks, `analytics >> report`, both in the `duckdb_writer` pool. `analytics` runs `dbt build --select tag:analytics`: the seven Python models of `dbt/models/analytics/` (snapshots, predictions, calibration maps, the backtest sample, metrics, reliability bins and the spread scores) and their tests. It has no retries, because the verdict of a failed gate does not change. `report` then runs `scripts/make_report.py` with the dbt virtualenv, reading `oap.duckdb` read-only. It is the container's copy of the report: it writes `results.md` and `img/*.png` to `.dbt-local/report/` on the host (the directory is mounted), never to `docs/`.

Run it by hand, which is the way to rerun it after fixing a failure, because nothing in bronze changed and no Dataset event will fire:

```bash
docker compose exec -T airflow-scheduler airflow dags unpause score_spreads   # once
docker compose exec -T airflow-scheduler airflow dags trigger score_spreads
docker compose exec -T airflow-scheduler airflow dags list-runs -d score_spreads
ls -l .dbt-local/report .dbt-local/report/img
```

Triggering `score_spreads` by hand builds the analytics over whatever gold holds now. It does not rebuild gold: after a bronze change, trigger `dbt_build` and let it start `score_spreads`, so the analytics never read a gold table that failed its tests.

The same models can be built from the host, which is what `make dbt-build-local` does for the whole project. For the analytics alone (stop both DAGs first, or pause them; only one writer):

```bash
OAP_DBT_SOURCE=iceberg OAP_ICEBERG_LOCAL_DIR=$PWD/.iceberg-local OAP_DUCKDB_PATH=$PWD/.dbt-local/oap.duckdb \
  uv run dbt build --project-dir dbt --profiles-dir dbt --target dev --select tag:analytics
```

**`make report`** writes the committed copy: `docs/results.md`, `docs/img/calibration.png` and `docs/img/spread_scores.png`, and replaces the text between `<!-- results:start -->` and `<!-- results:end -->` in `README.md` with the overall out-of-sample metrics and the top three spreads. It reads `.dbt-local/oap.duckdb` read-only, so run it after `make dbt-build-local` or after a `score_spreads` run has finished, and not while either DAG is running. The output is deterministic: a second run on the same database leaves `git diff` empty. Review the diff, then commit `docs/results.md`, `docs/img/` and `README.md`. The report holds derived statistics and a few derived spread rows, never raw vendor quotes.

```bash
make report
git diff --stat docs README.md
```

`make_report.py` exits with 2 and a message when it cannot proceed:

| Message | Cause | Fix |
| --- | --- | --- |
| `.dbt-local/oap.duckdb does not exist: run make dbt-build-local first` | No build has written the file. | `make dbt-build-local`, or wait for `score_spreads`. |
| `gold tables missing: ...` | The file holds silver and gold but not the analytics. | Trigger `score_spreads`, or run the host command above. |
| `cannot open ... (is a build writing it?)` | A build holds the write lock. | Wait for the running DAG (`list-runs --state running`) and retry. |
| `README excerpt not written: ...` | `README.md` lost a results marker. | Restore both marker comments, with the start marker first. |

**After the edge columns were added** (ADR 0013), `spread_scores` gained `fair_credit`, `edge`, `payoff_std`, `reward_to_risk`, `pop_implied`, `pop_gap` and the ranks `rank_edge`, `rank_rr` and `rank_entry`, among others. The API reads them by name, so against a gold file built before the change `/api/spreads` answers `503 gold_missing`. After merging, run `make dbt-build-local` (stop `make serve` first) before restarting the API; a `make pull-gold` artifact older than the merge has the same problem, and the next nightly run produces a good one. `make report` then adds the "Top 10 to enter" and "Top spreads by edge" sections to `docs/results.md`; the README excerpt does not change.

### Build on the host

```bash
make dbt-build-local
```

This runs `dbt deps`, then `dbt build` on the real local catalog (`OAP_DBT_SOURCE=iceberg`, `OAP_ICEBERG_LOCAL_DIR=.iceberg-local`) into `.dbt-local/oap.duckdb`, the same file the DAGs write. It builds silver, gold and the seven analytics models, with every test, and needs both bronze tables to exist. The first run downloads the DuckDB iceberg, avro and sqlite extensions into `~/.duckdb/extensions`, so it needs network once. Stop `dbt_build` and `score_spreads` first (see "One writer"). The silver and gold part took about 12 seconds on 1.48 million option rows; no timing is recorded for the analytics. Follow it with `make report` to write `docs/results.md`.

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
| `assert_fct_option_quote_matches_silver` | Gold differs from silver for some trade date, in row count or in the sum of `underlying_close`: a bronze slice was deleted, or a chain or price slice changed without a newer write time, so the incremental watermark skipped it. | Trigger `dbt_build` with `{"full_refresh": true}`. |
| `assert_calibration_out_of_sample` (analytics) | A fold map was fitted on an expiration on or after its own year start, or on or after the first trade date it is applied to. That is leakage: the walk-forward rule in `oap.analytics.backtest` or the model that calls it was changed. | Do not loosen the test. Find the change (`git log -p src/oap/analytics/backtest.py dbt/models/analytics/`) and fix the training mask. |
| `assert_calibration_map_monotone` (analytics) | A calibration map has a knot that does not increase, or a calibrated value that falls. The isotonic fit or the knot compaction broke. | Read the rows the test returns, then reproduce with `uv run pytest tests/analytics/test_backtest.py -q`. |
| `assert_predictions_from_ok_snapshots` or `assert_spread_rank_contiguous` (analytics) | A prediction exists for an excluded snapshot, or the ranks of eligible spreads have a gap or a rank on an ineligible spread. | A logic error in `oap.analytics`, not a data problem. The test output lists the rows. |
| `unique_combination_of_columns` or `accepted_values` on an analytics model | A new snapshot status, or duplicate keys in a model's output. | Check the exclusion rules in `calibration_snapshot` against `src/oap/analytics/config.py` before touching the test. |
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

## Explorer

The explorer is a FastAPI service (`src/oap/api/`) and a React app (`apps/web/`) over the gold tables of `.dbt-local/oap.duckdb`. It is a host process, not part of the Compose stack, and it binds `127.0.0.1` only. The spread table and scatter show return on max loss (labelled "E[R/max loss]" and "Ann. R/max loss"); it is the gold columns `expected_roc` and `annualised_roc`, and the collateral held equals the max loss. The design is in [ADR 0011](decisions/0011-explorer-react-fastapi.md) and [design/explorer-v1.md](design/explorer-v1.md).

### Start and stop

| Command | Starts | Notes |
| --- | --- | --- |
| `make app` | The API on `127.0.0.1:8000` with reload, and Vite on `localhost:5173` | Open http://localhost:5173. Vite proxies `/api` and `/healthz` to the API. Ctrl-C stops both. Installs `apps/web/node_modules` on first use (`npm ci`, Node 22 or later). |
| `make serve` | The API on `127.0.0.1:8000`, with the built web app mounted at `/` | Builds `apps/web/dist` first. Deep links such as `/spreads` return the app shell. |
| `make api` | The API alone | `uvicorn oap.api.main:app --reload --reload-dir src`; it reloads on code changes only, not when dbt writes `.dbt-local`. |
| `make web` | Vite alone | Needs the API on port 8000. |

`make api`, `make app` and `make serve` read `.dbt-local/oap.duckdb`. To read another file, set `OAP_DUCKDB_PATH`. `OAP_WEB_DIST` moves the web build directory, and `OAP_API_CORS_ORIGINS` (comma-separated origins) turns on CORS; without it no CORS middleware is added, and the dev server does not need one. Without `apps/web/dist/index.html`, `GET /` answers a JSON 404 that says to run `make web-build`.

### The database lock

DuckDB lets one process write or many read, never both at once. The API opens the file read-only, runs its queries and closes it in the same call, one connection at a time. After the first load of an underlying (a fraction of a second to about a second cold, milliseconds warm) every request is served from memory, so scrubbing and playing a session sequence open nothing. The cache is keyed by the file's modification time and size, so a build invalidates it.

**Do not leave the explorer playing during `make dbt-build-local`.** A load that lands while the writer holds the lock is refused, and a load that holds the file for a moment can make a writer's open fail; `dbt_build` has `retries=1` with a 2-minute delay, a host build has none. Pause playback and wait for the build to end.

What a request sees while a writer holds the file:

| Situation | Response |
| --- | --- |
| The data was loaded before and is in memory | `200` with the header `X-OAP-Data-Stale: 1`. The web app shows "Showing cached data while dbt writes". |
| The data is not in memory (a first load, or an underlying not opened yet) | `503`, `Retry-After: 15`, body `{"code": "database_busy", ...}`. The web app retries by itself, at most 8 times, and keeps the last frame. |
| The file does not exist | `503` `database_missing`, no `Retry-After`: run `make dbt-build-local`. |
| A gold table or column is missing | `503` `gold_missing`: the file is from an older build; rebuild it. |

Once the writer is done the next request reloads from the new file and the header disappears. `GET /healthz` always answers `200` with `{"status": "ok", "db": "ok" | "busy" | "missing", "db_path": ..., "last_good_signature_at": ...}`, so it is safe to poll. Check it first when something looks wrong:

```bash
curl -s http://127.0.0.1:8000/healthz
curl -si http://127.0.0.1:8000/api/underlyings | head -5
```

File locks may not propagate across a Colima bind mount, so the lock protection above is tested for host processes only. When `dbt_build` or `score_spreads` runs in the container, pause playback by hand; the API cannot always tell that the writer is active.

### Calibration map choice

`map=auto` (the default) uses the `production` map for the latest session and `fold_<year>` for any earlier one, so a historic session is not shown through a map that has seen its outcome. `production` and `walk_forward` force one or the other. A response says which map it used (`map_id`) and whether the map was fitted on outcomes that settle after the session (`look_ahead`); the web app shows that as an "in-sample map" chip. `fold_2020` is the identity (the burn-in year), and the app says "no calibration (2020 burn-in)" for it.

### Regenerate the API schema

The web app's types are generated from the API. After changing a model or a route in `src/oap/api/`:

```bash
make api-schema      # writes apps/web/openapi.json, then apps/web/src/api/schema.ts
```

Commit both files. `uv run pytest tests/api/test_openapi.py` fails, and says to run `make api-schema`, when `openapi.json` is out of date; `npm --prefix apps/web run check:api` fails when `schema.ts` is.

### Tests

`uv run pytest tests/api -q` runs the API tests against a small gold schema built in a temporary DuckDB file, including a test that holds the write lock from a subprocess. `make web-check` runs the web app's checks and build. `make check` includes the API tests and not the web checks.

### Explorer failures

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The page says "dbt is writing the database. Retrying in 15 s" | A build or `score_spreads` holds `oap.duckdb`. | Wait. It retries and recovers by itself. |
| The page says "No gold data yet" | `.dbt-local/oap.duckdb` does not exist or has no gold schema. | `make dbt-build-local`. |
| `make app` fails with "port 8000 is already in use" or `--strictPort` fails on 5173 | An earlier server is still running. | `lsof -i :8000` or `lsof -i :5173`, stop the holder. |
| `GET /` returns `The web app is not built` | `make serve` was not used, or `apps/web/dist` is gone. | `make web-build`, or use `make app`. |
| `make dbt-build-local` fails with `Could not set lock` while the explorer runs | The API was loading at that moment. | Run the build again; stop playback first. |
| `tests/api/test_openapi.py` fails | A model or route changed without regenerating the schema. | `make api-schema`, then commit `apps/web/openapi.json` and `src/api/schema.ts`. |

## Nightly cloud refresh

`.github/workflows/nightly.yml` refreshes the data without the laptop ([ADR 0012](decisions/0012-nightly-cloud-refresh.md)). It is a second path to the same bronze tables and the same gold schema as the Airflow stack, which stays the reference pipeline. The two can differ by a day.

### How it runs

The workflow `nightly` starts at 06:30 UTC, Tuesday to Saturday, an hour after DoltHub publishes the previous session. One job, `refresh`, has a 180-minute timeout and never runs twice at once (a second run waits).

| Step | What it does |
| --- | --- |
| Restore | Restores `.iceberg-local/` from the newest Actions cache whose key starts with `iceberg-`. |
| Refresh | `scripts/refresh_bronze.py`. With a restored warehouse: the last 10 sessions of both tables. Without one, or with `full_history`: everything from 2020-01-01. The step prints `path: ...` to say which. An explicit `start` input uses that window instead. |
| Save | Saves the warehouse under a new `iceberg-<run id>-<attempt>` key, straight after a successful refresh, so a failed build keeps the new bronze. A failed refresh saves nothing. |
| Build | `make dbt-build-local` with `OAP_DUCKDB_MEMORY_LIMIT=4GB` and `OAP_DUCKDB_THREADS=2`: silver, gold and the analytics, with every test. Then `make report`. |
| Publish | Uploads the artifacts `gold-duckdb` (`oap.duckdb`) and `results` (the report), both kept 14 days. If `docs/results.md`, the two figures or `README.md` changed, commits those four paths to `main` as `chore(results): nightly refresh through <max trade_date>`. Nothing else is ever committed. |

The run's summary page shows the path taken, the refresh summary line and the latest `trade_date` in gold. A run started from a branch other than `main` builds everything and uploads the artifacts, but does not commit.

`scripts/refresh_bronze.py` also runs by hand against any catalog the environment selects, for example into a scratch warehouse:

```bash
OAP_ICEBERG_URI=sqlite:////tmp/scratch/catalog.db OAP_ICEBERG_WAREHOUSE=file:///tmp/scratch/warehouse \
  uv run python scripts/refresh_bronze.py --start 2026-10-13 --end 2026-10-16 --symbols SPY --tables prices
```

Without `OAP_ICEBERG_*` it writes to `.iceberg-local/`, the Airflow stack's warehouse, so stop `backfill_*` and `daily_*` first (see "The `bronze_writers` pool"). It exits 1 if any fetch failed after the client's own retries, and prints which; everything that did arrive is already written, and running it again is safe.

### Trigger it by hand

```bash
make nightly-run                                        # the default path
make nightly-run START=2026-10-01 END=2026-10-15        # an explicit window
make nightly-run FULL=1                                 # everything from 2020-01-01
make nightly-status                                     # the last five runs
```

These need the GitHub CLI (`gh auth login` once). The workflow file must be on the default branch for `gh workflow run` to find it. The Actions tab offers the same inputs.

### Pull the gold file to the laptop

```bash
make serve                  # if it runs, stop it (Ctrl-C), and stop dbt_build and score_spreads
make pull-gold              # replaces .dbt-local/oap.duckdb with the latest successful run's file
make serve                  # the explorer shows the new data
```

`make pull-gold` takes the `gold-duckdb` artifact of the latest successful `nightly` run, moves the current file to `.dbt-local/oap.duckdb.bak` (and its WAL, if any, to `.bak.wal`), puts the new one in place and prints its latest `trade_date`. **Only one process may use the file**, and the target cannot tell whether one does: a running explorer API keeps serving its cache from the old file, and a running `dbt_build` would write to a file that was just replaced. Stop them first.

Artifacts expire after 14 days. If the latest successful run is older, `pull-gold` says so; run `make nightly-run` and pull again once it finishes (`make nightly-status`).

The pulled file was built from the cloud's warehouse, not the laptop's. If the laptop warehouse is older than the cloud's, do not run `make dbt-build-local` over the pulled file without `--full-refresh`: the incremental `fct_option_quote` keeps only rows stamped later than the newest stamp it holds, and the cloud's stamps are later than the laptop's. To go back, `mv .dbt-local/oap.duckdb.bak .dbt-local/oap.duckdb`.

### When the cache was evicted

GitHub evicts a cache entry that has not been used for 7 days, and the repository's total above 10 GB. A holiday week, a disabled workflow or a stretch of failed runs can empty it. The next run restores nothing, prints `path: full history, because no warehouse cache was restored`, and refetches 2020-01-01 to today with four workers, about 45 minutes (an estimate; check the first real run). Nothing needs doing: it is the same code as the nightly path with a wider window. To force it, `make nightly-run FULL=1`.

If that run fails part way (a DoltHub outage), no cache is saved and the next run starts the full history again. Slices that already landed are not rewritten, so only the fetching repeats.

GitHub disables scheduled workflows in a repository with no activity for 60 days. The nightly commits count as activity while they happen; if the schedule was switched off, enable it in the Actions tab and run `make nightly-run`.

### Cost

On a public repository, hosted runner minutes are free. A normal night restores the cache, fetches 10 sessions (one or two months, so a handful of queries per symbol) and builds gold, which is most of the time. No run has happened yet, so there is no measured duration; read it from the first runs in the Actions tab and record it here. A full-history night is the 45-minute fetch estimate above plus the same build. On a private repository a free account has 2,000 minutes a month: about 22 normal nights fit if each stays under an hour, and a full rebuild takes a large part of what is left.

### Failures

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The refresh step exits 1 and prints `failed: chains SPY 2026-10: ...` | DoltHub did not answer after six attempts, or returned rows that broke the bronze contract. | Re-run with `make nightly-run`. The merge is idempotent. If it repeats, query DoltHub by hand. |
| The date input is rejected | `start` or `end` is not `YYYY-MM-DD`. | Re-run with a valid date. |
| The build fails and the cache was saved | A dbt test failed on the new data. | Read the dbt log in the run; bronze is saved, so a re-run starts from it. Fix the model or the data, then `make nightly-run`. |
| `make pull-gold` says there is no successful run | The workflow has not succeeded yet, or is not on the default branch. | `make nightly-status`, then `make nightly-run`. |
| The commit step fails with a rejected push | `main` is protected, or moved while the job ran and the rebase conflicted. | Allow the pushing identity, or pull and re-run. |
| The pushed results commit has no CI run | Pushes with the default token do not start workflows. | Store a personal access token as the secret `NIGHTLY_PUSH_TOKEN`. |

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
make dbt-build      # dbt build on the synthetic bronze catalog, three passes, then the report to .dbt-local/report-synthetic
make dbt-build-local  # real bronze into .dbt-local/oap.duckdb (not while dbt_build or score_spreads runs)
make report         # docs/results.md, docs/img/*.png and the README excerpt, from oap.duckdb
make web-check      # explorer web app: lint, format, typecheck, tests, schema drift, build (not part of make check)
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

**`dbt` or `make report` cannot lock `oap.duckdb`.** Another process holds the file; see "One writer".

**`score_spreads` never starts.** It runs only on a `GOLD` update, and only a `build` run of `dbt_build` that passed its tests emits one. Check that `score_spreads` is unpaused, that the last `dbt_build` run succeeded and was not `mode=test`, and that `publish_gold` was not skipped (`airflow tasks states-for-dag-run dbt_build <run_id>`). To run it anyway, trigger it by hand (see "Analytics and the report").

**`score_spreads` fails in `analytics`.** A singular or column test of an analytics model failed. The task is not retried. Read the failing test in `.dbt-local/artifacts/run_results.json` (the snippet in "The `dbt_build` DAG") and see "dbt failures".

**`make report` writes a placeholder figure or empty tables.** The out-of-sample set or the latest session has no rows. Check `calibration_metrics` and `spread_scores` in a copy of the file; this happens on synthetic data and before the history is loaded.

**`dbt compile` cannot find packages.** Run `make dbt-deps`. Packages install to `dbt/dbt_packages/`, which is gitignored. In the Airflow image they are baked in at `/opt/dbt-packages/dbt_packages`.

**`dbt` on `prod` fails to connect.** One of the `SNOWFLAKE_*` variables is empty or unexported. Check with `env | grep SNOWFLAKE_ | sed 's/=.*/=.../'` so the password is not printed.

**`detect-secrets` blocks a commit.** Read the reported file and line. If it is a real secret, remove it and rotate it. If it is a false positive, run `uv run detect-secrets scan --baseline .secrets.baseline`, review the diff, and commit the updated baseline.
