# options-analytics-platform

Daily options chains land in Apache Iceberg tables on S3, are modeled with dbt on Snowflake, and feed a put credit spread engine. The engine extracts the market-implied probability distribution from vertical spread prices, calibrates it against realized outcomes since 2019, and scores every candidate spread on expected return on collateral, including interest on the cash that stays held (Robinhood Gold, 3.6% APY). The project exists to build that path end to end, from vendor data to a ranked decision, with a quality gate between every layer.

```
Alpaca ──> Airflow ──> Iceberg on S3 ──> dbt on Snowflake ──> spread engine
chains     daily DAG   bronze (raw)      silver ──> gold       src/oap/engine
                            │               │          │
                            └── Great Expectations gates ┘
```

**Status: Phase 0, scaffolding only.** The repo has the tooling, CI, a local Airflow stack, a dbt project with one seed and two models, and Terraform for the S3 bucket, Glue database and IAM user. There is no ingest or engine logic yet; Phase 1 will add the first.

## Quickstart

Needs Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker (Colima works on macOS).

```bash
uv sync --all-groups          # install dev, airflow and dbt dependency groups
make check                    # lint, typecheck, test, dbt compile
cp .env.example .env          # local settings; defaults work for Airflow
docker compose up -d          # Airflow UI at http://localhost:8080 (airflow / airflow)
```

`make check` needs no credentials: dbt compiles against a local DuckDB file. Operating instructions are in [docs/runbook.md](docs/runbook.md).

## Repo layout

| Path | Contents |
| --- | --- |
| `src/oap/` | The Python package: `ingest/` (vendor pulls and bronze writers), `engine/` (pure pricing and scoring functions), `quality/` (layer gates). Documented stubs in Phase 0. |
| `tests/` | pytest tests for the package, the DAGs and the dbt project, in paths that mirror the code. |
| `dags/` | Airflow DAGs and their shared defaults, mounted into the containers. Phase 0 has one smoke DAG. |
| `dbt/` | dbt project `oap`: seeds, staging and mart models, and a `profiles.yml` with a DuckDB `dev` and a Snowflake `prod` target. |
| `infra/` | Terraform for the S3 bucket, Glue catalog database and a scoped IAM user. |
| `docker/` | The Dockerfile for the on-demand dbt container. |
| `docs/` | Architecture notes, the operator runbook and decision records. |
| `.github/workflows/` | CI: the `check` job (`make check`) and the `infra` job (Terraform and Compose validation). |
| `.claude/` | Claude Code hooks, slash commands and agents for working in this repo. |

## Checks

`make check` runs the four checks below and must pass before every commit. CI runs the same target.

| Check | What it guards |
| --- | --- |
| `make lint` | `ruff` lint and format check: style drift and common bugs. |
| `make typecheck` | `mypy --strict` on `src/`, `tests/` and `dags/`: untyped or wrongly typed code, which matters most in the engine. |
| `make test` | `pytest` and `hypothesis`: behaviour and property invariants. |
| `make dbt-compile` | `dbt compile` on DuckDB: Jinja, refs and YAML in every model. It does not run SQL on Snowflake (see ADR 0002). |

`make tf-fmt`, `make tf-validate` and `make compose-config` check the Terraform and Compose files and run in the CI `infra` job. `pre-commit` (install once with `uv run pre-commit install`) runs `detect-secrets`, ruff and file hygiene hooks on each commit.

## Roadmap

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Scaffolding: tooling, CI, Airflow stack, dbt skeleton, Terraform. | Done |
| 1 | Ingest daily Alpaca options chains into Iceberg bronze on S3. | Next |
| 2 | dbt silver and gold models on Snowflake, with Great Expectations gates between layers. | Planned |
| 3 | Spread engine: implied distribution, calibration against 2019+ outcomes, expected return on collateral. | Planned |

Intraday streaming (a Redpanda service is stubbed out, commented, in `docker-compose.yml`) comes after Phase 3.

## Why these choices

- [0001: Medallion layering with Iceberg bronze on S3](docs/decisions/0001-medallion-on-iceberg.md). Raw history stays replayable and schema-flexible outside the warehouse.
- [0002: DuckDB as the local and CI dbt target](docs/decisions/0002-duckdb-for-local-dbt.md). `make check` works on a fresh clone with no credentials.

Architecture and data flow: [docs/architecture.md](docs/architecture.md). License: MIT.
