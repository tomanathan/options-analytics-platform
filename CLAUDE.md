# options-analytics-platform

Option chains and daily prices land in Iceberg (bronze), dbt builds silver and gold on DuckDB (Snowflake is the unprovisioned prod target), Airflow orchestrates, Great Expectations gates bronze, and a put credit spread engine scores spreads. See README.md and docs/architecture.md.
Status: Phases 0-2 built (two bronze tables, six DAGs, dbt silver/gold, `dbt_build` scheduled on Datasets). Phase 3 is in progress: `oap.engine` is built; backtest, scoring and report are not.

## Layout
- `src/oap/{ingest,engine,quality}/`, `src/oap/calendar.py` (NYSE calendar). `tests/` mirrors the code.
- `oap.ingest.tables`: one `TableSpec` per bronze table (`OPTION_CHAIN`, `UNDERLYING_PRICE`); writer, reader, merge and maintenance are generic over it.
- `src/oap/engine/`: pure numpy functions (conventions, black_scholes, implied_distribution, calibration, spread_scoring).
- `dags/`: DAGs plus `common.py` (defaults, pool, `fail_fast`), `datasets.py` (bronze Datasets), `timetables.py`. `plugins/oap_timetables.py` registers `NYSECloseTimetable`.
- `dbt/`: project `oap`. `models/{staging,intermediate}` are silver, `models/marts` is gold, `macros/register_bronze.sql` pins the Iceberg snapshot, `tests/` holds singular tests.
- `scripts/`: `iceberg_count.py`, `make_synthetic_bronze.py`, `image_requirements.py`. `docker/`: `airflow.Dockerfile`, generated `requirements*.txt`. `infra/`: Terraform. `docs/`: architecture, runbook, ADRs 0001-0009.

## Conventions
- Python 3.12, `uv`, `ruff` (Google docstrings), `mypy --strict`, `pytest` + `hypothesis`.
- Engine code is pure, no I/O. Every docstring states units: dollars per share, vol as decimal, time in years (ACT/365), rates as decimal APY (ADR 0009).
- A new bronze table is a new `TableSpec` in `oap.ingest.tables`; write only through `write_partition` or `merge_into_slices`, which overwrite the (trade_date, source) slice (ADR 0003).
- Any Airflow task that commits to bronze runs in `pool=BRONZE_WRITERS_POOL`. Put `@fail_fast` under `@task` so deterministic errors are not retried. A DAG that produces bronze data lists the Dataset in `outlets`.
- DAGs on the market calendar use `NYSECloseTimetable`, not cron. Do not import one DAG module from another.
- dbt resolves bronze through the `register_bronze` hook and `OAP_DBT_SOURCE` (ADR 0008); models read `source('bronze', ...)`, never file paths. Underlying prices are as traded, not split-adjusted (ADR 0007).
- dbt: every model has `schema.yml` descriptions on every column and at least two tests. Portable SQL for DuckDB and Snowflake; `adapter.dispatch` where they differ (ADR 0002).
- Dependency changes: edit `pyproject.toml`, `uv lock`, `make lock-export`, `make airflow-build`. The image installs from the lock (ADR 0006).
- Local Iceberg catalog is `oap.ingest.local_catalog` (stdlib sqlite3, ADR 0005). Terraform: commit `.terraform.lock.hcl`; no access key resources.
- Conventional commits: `feat(ingest): ...`, `chore(infra): ...`, `docs(decisions): ...`. Non-obvious design choices get a Nygard-format ADR.

## Checks
- `make check` (lock-check, lint, typecheck, test, dbt-compile, dbt-build on synthetic bronze) must be green before every commit.
- Also `make tf-validate`, `make compose-config`. pre-commit runs `detect-secrets`, ruff and hygiene hooks.
- Hooks: ruff formats every Python file you edit; `uv run pytest -q` runs when you stop and blocks on failures.
- Only one process may write `.dbt-local/oap.duckdb`; do not run `make dbt-build-local` while `dbt_build` runs.

## Adding things
- Python: `python` agent; test at the mirrored path. dbt model: `/model <layer> <name>`. DAG: `/dag`. Docs and ADRs: `docs` agent. Review: `/review`.

## Never
- Never commit data, `.env`, credentials, keys, state files or `*.duckdb`. `data/` and `.iceberg-local/` are gitignored.
- Never put real secrets in `.env.example`; use obvious placeholders.
- Never leave placeholder text or unfinished-work markers in code or docs; write "Phase N will ..." instead.
- Never describe unbuilt behaviour as existing. Never skip hooks (`--no-verify`).
