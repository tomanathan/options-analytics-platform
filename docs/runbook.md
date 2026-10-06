# Runbook

For whoever operates the stack. All commands run from the repo root unless noted. "Operating" means the Airflow stack, the Phase 1 bronze pipelines (backfill, daily snapshot, maintenance), dbt, Terraform and the checks.

## Airflow stack

Services: `postgres` (metadata DB), `airflow-init` (one-shot migrate and create user), `airflow-webserver`, `airflow-scheduler`. LocalExecutor. `make up`, `make down`, `make reset` and `make logs` wrap the commands below; `make down` keeps the metadata volume, `make reset` deletes it.

The containers receive `AWS_REGION`, `OAP_*` and `ALPACA_*` from `.env`. By default the DAGs write to the local Iceberg catalog; see "Local and AWS catalog" below for switching to S3 and Glue. `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are passed through from the shell that runs `docker compose`, not from `.env`.

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

## Phase 1: bronze pipelines

Three DAGs write and maintain `bronze.option_chain`: `backfill_chains` (history from DoltHub, triggered by hand), `daily_chain_snapshot` (Alpaca snapshot after the NYSE close) and `iceberg_maintenance` (weekly). The table design and the overwrite rule are in [architecture.md](architecture.md) and [ADR 0003](decisions/0003-partition-overwrite-for-idempotency.md). Locally the table lives in `.iceberg-local/` (gitignored); inside the containers that directory is mounted at `/opt/airflow/.iceberg-local`. The local catalog is a standard-library SQLite file, `.iceberg-local/catalog.db` ([ADR 0005](decisions/0005-stdlib-sqlite-local-catalog.md)); it supports one writer host, so do not point two machines at one file. Iceberg metadata records container-absolute file paths, so read the table from inside the containers (`make iceberg-count`), not from the host. If `ensure_table` raises `ValueError` about a column type after a schema change (Iceberg cannot change a decimal's scale in place), stop the stack, delete `.iceberg-local/` and re-run the backfill; nothing in that directory is a source of truth.

### Build the Airflow image

All Airflow services share one image, `oap-airflow:dev`, built from `docker/airflow.Dockerfile`: the official image plus `pip install .`, so the dependencies of `oap` (pyiceberg, Great Expectations, pandas) are baked in. Any change to the dependencies in `pyproject.toml` needs a rebuild. Python edits under `src/` do not, because `src/`, `dags/`, `plugins/` and `scripts/` are mounted.

```bash
make airflow-build
make up
```

`make up` builds the image only if it does not exist yet. If a DAG fails with `ModuleNotFoundError` for a third-party package, the image is stale: run `make airflow-build`, then `make up` again to recreate the containers.

### Run a backfill for one month

```bash
make backfill START=2024-01-01 END=2024-01-31
make backfill START=2024-01-01 END=2024-03-31 SYMBOLS=SPY,QQQ
```

`SYMBOLS` defaults to the watchlist seed (`dbt/seeds/watchlist.csv`, mounted read-only into the containers). The make target unpauses the DAG and triggers it with the dates as run parameters. The equivalent direct commands:

```bash
docker compose exec -T airflow-scheduler airflow dags unpause backfill_chains
docker compose exec -T airflow-scheduler airflow dags trigger backfill_chains \
  --conf '{"start": "2024-01-01", "end": "2024-01-31", "symbols": ["SPY", "QQQ"]}'
```

An empty `symbols` list means the watchlist. The DAG plans one fetch task per (symbol, month) with at least one NYSE session in range, runs at most 4 tasks at once, and retries each fetch up to 5 times with exponential backoff (capped at 10 minutes). A fetch that finds no rows in DoltHub ends as `skipped`, not failed, and leaves whatever that symbol already has in the table untouched: absence in a response is never treated as a deletion (ADR 0003). Coverage for the watchlist starts in 2020 and has scattered missing trading days, so a range before 2020 produces skipped fetches only. After the fetches, one write task per month merges the staged symbols into each day's slice and overwrites it, one month at a time. A write for a month is skipped over any slice whose content did not change, so repeating a backfill adds no snapshots. Only one backfill run is active at a time; a second trigger waits.

DoltHub notes: range predicates on `date` time out, so the client queries each month with an explicit list of trading days and pages with `LIMIT 1000 OFFSET n`. With an explicit `LIMIT`, DoltHub reports a full page as `Success` rather than `RowLimit`, so the client keeps paging while a page holds exactly 1000 rows. Timeouts, HTTP 429 and 5xx responses are retried inside the client before Airflow's own retries begin. Rows with a crossed quote (bid above ask) are dropped with a logged `WARNING` giving the count per underlying and date.

### Re-run a failed day

Run the backfill for that single date:

```bash
make backfill START=2024-01-17 END=2024-01-17 SYMBOLS=SPY
```

This is safe to repeat. Each write replaces the (trade_date, source) slice and never appends, so the re-run produces the same rows as a clean run and leaves no duplicates (ADR 0003). Other symbols already in the slice are kept. `ingested_at` differs when a slice is rewritten; `make iceberg-count` prints a content hash that excludes it. If a month's write task fails with "fetch failed for ...", one of its fetches did not finish; its slices were left untouched, so re-run that month.

A failed `daily_chain_snapshot` task is retried by clearing it in the UI grid or with `airflow tasks clear`. Alpaca returns the latest snapshot, so a run triggered long after its session stores the quotes of the trigger time under that session's date. Re-run an Alpaca session the same evening or not at all. To fill a missed past day, use the DoltHub backfill, with its column limits (no last, volume, open interest or underlying price).

### Watch progress

```bash
docker compose exec -T airflow-scheduler airflow dags list-runs -d backfill_chains
docker compose exec -T airflow-scheduler airflow tasks states-for-dag-run backfill_chains <run_id>
```

Get `<run_id>` from `list-runs`. `states-for-dag-run` prints one line per task instance and map index; count the states of `fetch_month` to see how many (symbol, month) tasks are `success`, `running`, `up_for_retry`, `skipped` or `failed`, and those of `write_month` for the months. In the UI (http://localhost:8080), open the DAG, then Grid: each mapped task shows a count badge, and clicking it lists each map index with its logs. Logs are also on disk under `logs/airflow/`. The `summarize` task logs the totals.

### Count what landed

```bash
make iceberg-count
make iceberg-count ARGS="--source dolthub --start 2024-01-01 --end 2024-01-31"
```

This runs `scripts/iceberg_count.py` in the scheduler container and prints one line per (source, trade_date) with its row count, then the total and a `content_hash` of the selected rows. Use the counts to confirm that expected days exist and that no day is unexpectedly low. Run the same command before and after a re-run: an unchanged hash shows the re-run was a no-op. The script exits with an error if the table does not exist yet (nothing has been written).

### Quality failures

The `quality` task of `daily_chain_snapshot` reads the written slice back and runs the bronze suite (`src/oap/quality/bronze_suite.py`) against the previous 20 sessions of the same source. A failed expectation raises `BronzeQualityError`, naming the failed expectations, and fails the task. The backfill DAG does not run the suite in Phase 1; check its output with `make iceberg-count`. A failure does not roll back the write: the slice stays as written until it is re-run. Frames are also validated against the bronze contract before every write (bid not above ask, expiration not before trade date, unique key, strike above zero, right in C/P); a violation fails the write task with the list of failed checks and commits nothing.

**`row_count:<SYMBOL>`.** The underlying's row count for the day is outside the band: within 50% of the median over its previous 20 sessions. Underlyings with fewer than 5 days of history are not bounded.
- Below the band: usually a vendor outage or a partial response. Re-run the day (the same evening for Alpaca). If it stays low, check the vendor directly.
- Above the band: new expirations were listed, or the same data was written under two source tags. Inspect the slice with `make iceberg-count` before re-running.

**`occ_symbol_not_null`.** The parser failed to build the compact OCC symbol for some rows. This is a bug in `src/oap/ingest/`, not a data problem. Do not re-run until the parser is fixed, because the re-run overwrites with the same bad rows.

**`strike_positive` or `right_in_set`.** Malformed vendor rows or a column mapping error. Read the failing expectation in the task log. If the vendor changed a format, fix the mapping, then re-run.

**`key_unique`.** Duplicates on (occ_symbol, trade_date, source). The overwrite rule should make this impossible within one source tag. It means two writers used the same `source` value, or the vendor sent the same contract twice. Check the `source` column of the slice; if a writer is tagging with the wrong source, fix it and re-run both days.

### Maintenance DAG

`iceberg_maintenance` runs weekly. First it expires snapshots older than 7 days, always keeping the current one. Then it compacts: any (trade_date, source) slice with more than one data file is read and written back through the same overwrite path, because pyiceberg 0.12 has no `rewrite_data_files`; the rows, including `ingested_at`, are unchanged. Run it by hand:

```bash
docker compose exec -T airflow-scheduler airflow dags unpause iceberg_maintenance
docker compose exec -T airflow-scheduler airflow dags trigger iceberg_maintenance
```

Run it after a large backfill: retries and re-runs leave replaced data files referenced by old snapshots until they expire. Expiring snapshots limits time travel to 7 days.

### Local and AWS catalog

The catalog is chosen by environment variables (set them in `.env`; Compose passes them to the containers):

| Variable | Local (default) | AWS |
| --- | --- | --- |
| `OAP_ICEBERG_CATALOG` | `sql` (alias `local`) | `glue` |
| `OAP_ICEBERG_URI` | `sqlite:///.iceberg-local/catalog.db` | not used |
| `OAP_ICEBERG_WAREHOUSE` | `file://./.iceberg-local/warehouse` | `s3://<bucket>/bronze` |
| `OAP_GLUE_DATABASE` | not used | `oap_bronze` (the table's namespace) |

In AWS mode the table is `<OAP_GLUE_DATABASE>.option_chain`. The containers cannot read `~/.aws` profiles, so export `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` for the `oap-pipeline` user in the shell that runs `docker compose`, together with `AWS_REGION`. Switching also needs the Terraform resources applied. The local and AWS tables are separate; nothing copies one to the other.

### Full history backfill

One command, run overnight:

```bash
make backfill START=2020-01-01 END=<yesterday as YYYY-MM-DD>
```

For 11 symbols over about 81 months that is roughly 900 fetch tasks at 4 concurrent, about one hour when DoltHub answers quickly. DoltHub rate limits can stretch it. The run is resumable: if tasks fail after their retries, re-run the same command; unchanged slices are skipped and the overwrite rule makes the repeat safe. Finish with `make iceberg-count` and the maintenance DAG.

## dbt

Locally, on the DuckDB `dev` target. No credentials are needed:

```bash
make dbt-deps        # install dbt_utils and dbt_expectations
make dbt-compile
```

`make dbt-compile` also runs `dbt deps`. Other dbt commands use the same project and profile directory, for example:

```bash
uv run dbt build --project-dir dbt --profiles-dir dbt --target dev
```

`dbt build` on `dev` writes `.dbt-local/oap.duckdb` (run `mkdir -p .dbt-local` first on a clean clone). Delete that file to start over; it is gitignored.

In the container (the `dbt` service is under the `tools` profile, so `docker compose up` does not start it). The container mounts `./dbt` and `./.dbt-local`, so packages and the DuckDB file persist on the host:

```bash
mkdir -p .dbt-local
docker compose run --rm dbt deps
docker compose run --rm dbt compile
```

Against Snowflake (`prod`), set the `SNOWFLAKE_*` variables in `.env`. The container picks them up through Compose:

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
make check          # lint, typecheck, test, dbt-compile
make tf-fmt         # needs terraform on PATH
make tf-validate
make compose-config # needs docker on PATH
uv run pre-commit install   # once per clone: runs the hooks on every commit
```

`make format` rewrites files with ruff. `make clean` removes caches, build output, `.dbt-local` and `.venv`, so the next `make install` starts from scratch.

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

**`dbt compile` cannot find packages.** Run `make dbt-deps`. Packages install to `dbt/dbt_packages/`, which is gitignored.

**`dbt` on `prod` fails to connect.** One of the `SNOWFLAKE_*` variables is empty or unexported. Check with `env | grep SNOWFLAKE_ | sed 's/=.*/=.../'` so the password is not printed.

**`detect-secrets` blocks a commit.** Read the reported file and line. If it is a real secret, remove it and rotate it. If it is a false positive, run `uv run detect-secrets scan --baseline .secrets.baseline`, review the diff, and commit the updated baseline.
