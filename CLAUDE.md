# options-analytics-platform

Options chains go to Iceberg on S3 (bronze), dbt on Snowflake (silver/gold), orchestrated by Airflow with Great Expectations gates.
On top sits a put credit spread engine: market-implied distribution from vertical spreads, calibrated on 2019+ outcomes, scored on return on collateral.
Phase 0 is scaffolding only; no pipeline or engine logic exists yet. See README.md and docs/architecture.md.

## Layout
- `src/oap/{ingest,engine,quality}/`: Python package. `tests/`: pytest + hypothesis, mirrors the code.
- `dags/`: Airflow DAGs. `dbt/`: dbt project `oap` (`profiles.yml` committed, no secrets).
- `infra/`: Terraform (S3, Glue, scoped IAM user). `docker/`: Dockerfiles. `docker-compose.yml`: Airflow stack.
- `docs/`: architecture, runbook, ADRs in `docs/decisions/`. `.claude/`: hooks, commands, agents.

## Conventions
- Python 3.12, `uv` (`uv sync --all-groups`), `ruff` lint+format (Google docstrings), `mypy --strict`, `pytest` + `hypothesis`.
- Engine code is pure functions, no I/O. Every docstring states units: prices in dollars, vol as decimal, time in years.
- Dependency groups: `dev`, `airflow` (apache-airflow==2.11.2), `dbt`.
- dbt: every model has `schema.yml` descriptions on every column and at least two tests. `dev` target is DuckDB, `prod` is Snowflake.
- Write portable SQL for DuckDB and Snowflake; use `adapter.dispatch` where they differ (ADR 0002).
- Terraform: commit `.terraform.lock.hcl`; no access key resources, keys are created by hand.
- Conventional commits: `feat(ingest): ...`, `chore(infra): ...`, `docs(decisions): ...`.
- Non-obvious design choices get an ADR in `docs/decisions/` (Nygard format, numbered).

## Checks
- `make check` (lint, typecheck, test, dbt-compile) must be green before every commit.
- Also: `make tf-validate`, `make compose-config`. pre-commit runs `detect-secrets`, ruff and hygiene hooks.
- Hooks: ruff runs on every Python file you edit; `uv run pytest -q` runs when you stop.

## Adding things
- New Python module: use the `python` agent; add a test at the mirrored path under `tests/`; stubs hold a docstring only.
- New dbt model: `/model <layer> <name>` (adds the SQL, `schema.yml`, tests and docs block).
- New DAG: `/dag`. DAGs must import cleanly in the scheduler container.
- Docs and ADRs: the `docs` agent. Review before commit: `/review`.

## Never
- Never commit data, `.env`, credentials, keys, state files or `*.duckdb`. `data/` is gitignored.
- Never put real secrets in `.env.example`; use obvious placeholders.
- Never leave placeholder text or unfinished-work markers in code or docs; write "Phase N will ..." instead.
- Never describe unbuilt behaviour as existing. Never skip hooks (`--no-verify`) to get a commit through.
