# Runbook

For whoever operates the stack. All commands run from the repo root unless noted. Phase 0 has no pipelines, so "operating" means the Airflow stack, dbt, Terraform and the checks.

## Airflow stack

Services: `postgres` (metadata DB), `airflow-init` (one-shot migrate and create user), `airflow-webserver`, `airflow-scheduler`. LocalExecutor. `make up`, `make down`, `make reset` and `make logs` wrap the commands below; `make down` keeps the metadata volume, `make reset` deletes it.

The containers receive `AWS_REGION`, `OAP_*` and `ALPACA_*` from `.env`. They get no AWS credentials in Phase 0, so DAGs cannot reach S3 yet; Phase 1 will add that.

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

**`dbt compile` cannot find packages.** Run `make dbt-deps`. Packages install to `dbt/dbt_packages/`, which is gitignored.

**`dbt` on `prod` fails to connect.** One of the `SNOWFLAKE_*` variables is empty or unexported. Check with `env | grep SNOWFLAKE_ | sed 's/=.*/=.../'` so the password is not printed.

**`detect-secrets` blocks a commit.** Read the reported file and line. If it is a real secret, remove it and rotate it. If it is a false positive, run `uv run detect-secrets scan --baseline .secrets.baseline`, review the diff, and commit the updated baseline.
