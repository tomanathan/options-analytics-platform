SHELL := /bin/bash
.DEFAULT_GOAL := help

DBT_ARGS := --project-dir dbt --profiles-dir dbt
# The Airflow image installs the runtime closure of uv.lock; --no-default-groups leaves out
# Airflow and dbt, which the image already is or does not need. Pinned uv keeps the text stable.
UV_EXPORT := uv export --frozen --no-default-groups --no-emit-project --no-hashes --no-header --format requirements.txt
# dbt runs from its own virtualenv in the image (docker/airflow.Dockerfile); this is that venv's lock.
UV_EXPORT_DBT := uv export --frozen --only-group dbt --no-emit-project --no-hashes --no-header --format requirements.txt

# dbt builds on a synthetic Iceberg bronze catalog (written by scripts/make_synthetic_bronze.py through the
# real writer), in its own DuckDB file, so `make check` needs no vendor data and never touches oap.duckdb.
SYNTHETIC_DIR := .dbt-local/synthetic-iceberg
DBT_SYNTHETIC_ENV := OAP_DBT_SOURCE=synthetic OAP_SYNTHETIC_BRONZE_DIR=$(CURDIR)/$(SYNTHETIC_DIR) OAP_DUCKDB_PATH=$(CURDIR)/.dbt-local/synthetic.duckdb
DBT_LOCAL_ENV := OAP_DBT_SOURCE=iceberg OAP_ICEBERG_LOCAL_DIR=$(CURDIR)/.iceberg-local OAP_DUCKDB_PATH=$(CURDIR)/.dbt-local/oap.duckdb

.PHONY: help install lint format typecheck test dbt-deps synthetic-bronze dbt-compile dbt-build dbt-build-local check \
	tf-fmt tf-validate compose-config lock-export lock-check airflow-build up down reset logs \
	backfill iceberg-count clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependency groups into .venv
	uv sync --all-groups

lint: ## Run ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-fix lint issues and format code
	uv run ruff check --fix . && uv run ruff format .

typecheck: ## Run mypy --strict
	uv run mypy

test: ## Run the pytest suite
	uv run pytest -q

dbt-deps: ## Install dbt packages
	uv run dbt deps $(DBT_ARGS)

synthetic-bronze: ## Write the synthetic Iceberg bronze catalog dbt builds on in make check
	mkdir -p .dbt-local
	uv run python scripts/make_synthetic_bronze.py --out $(SYNTHETIC_DIR)

dbt-compile: dbt-deps ## Compile dbt models against the local DuckDB dev target
	mkdir -p .dbt-local
	$(DBT_SYNTHETIC_ENV) uv run dbt compile $(DBT_ARGS) --target dev

# Two passes: the second runs the incremental model again over the data the first one loaded,
# which exercises its is_incremental() branch.
dbt-build: dbt-deps synthetic-bronze ## Seed, run and test dbt on the synthetic bronze catalog (DuckDB dev target)
	rm -f .dbt-local/synthetic.duckdb .dbt-local/synthetic.duckdb.wal
	$(DBT_SYNTHETIC_ENV) uv run dbt build $(DBT_ARGS) --target dev
	$(DBT_SYNTHETIC_ENV) uv run dbt build $(DBT_ARGS) --target dev --select config.materialized:incremental

dbt-build-local: dbt-deps ## Build dbt on the real local Iceberg catalog into .dbt-local/oap.duckdb (not while dbt_build runs)
	mkdir -p .dbt-local
	$(DBT_LOCAL_ENV) uv run dbt build $(DBT_ARGS) --target dev

check: lock-check lint typecheck test dbt-compile dbt-build ## The gate before every commit

tf-fmt: ## Check Terraform formatting
	terraform -chdir=infra fmt -check -recursive

tf-validate: ## Validate Terraform without a backend
	terraform -chdir=infra init -backend=false -input=false >/dev/null && terraform -chdir=infra validate

compose-config: ## Validate docker-compose.yml
	docker compose config --quiet

lock-export: ## Regenerate docker/requirements.txt and docker/requirements-dbt.txt from uv.lock
	$(UV_EXPORT) > docker/requirements.txt
	$(UV_EXPORT_DBT) > docker/requirements-dbt.txt

lock-check: ## Fail if docker/requirements.txt or docker/requirements-dbt.txt is stale
	@$(UV_EXPORT) | diff -u docker/requirements.txt - || { echo "docker/requirements.txt is out of date with uv.lock: run make lock-export" >&2; exit 1; }
	@$(UV_EXPORT_DBT) | diff -u docker/requirements-dbt.txt - || { echo "docker/requirements-dbt.txt is out of date with uv.lock: run make lock-export" >&2; exit 1; }

airflow-build: ## Build the Airflow image (one image serves every Airflow service)
	docker compose build airflow-webserver

# Builds the image on first use only; run `make airflow-build` after dependency changes.
up: ## Start the local Airflow stack
	mkdir -p .iceberg-local .dbt-local logs/airflow
	docker compose up -d

down: ## Stop the stack, keeping the Postgres metadata volume
	docker compose down --remove-orphans

reset: ## Stop the stack and delete its volumes (fresh Airflow metadata DB on next up)
	docker compose down -v --remove-orphans

logs: ## Tail logs from the stack
	docker compose logs -f --tail=100

backfill: ## Backfill DoltHub history: make backfill START=YYYY-MM-DD END=YYYY-MM-DD [SYMBOLS=SPY,DIA]
	@if [ -z "$(START)" ] || [ -z "$(END)" ]; then \
		echo "usage: make backfill START=YYYY-MM-DD END=YYYY-MM-DD [SYMBOLS=SPY,DIA] (no SYMBOLS = watchlist)" >&2; \
		exit 1; \
	fi
	docker compose exec -T airflow-scheduler airflow dags unpause backfill_chains
	symbols=$$(printf '%s' "$(SYMBOLS)" | awk -v RS=, 'NF { printf "%s\"%s\"", sep, $$1; sep = "," }'); \
	docker compose exec -T airflow-scheduler airflow dags trigger backfill_chains \
		--conf "{\"start\":\"$(START)\",\"end\":\"$(END)\",\"symbols\":[$$symbols]}"

iceberg-count: ## Bronze rows per slice and underlying; ARGS="--summary" or "--hash" or "--source dolthub"
	docker compose exec -T airflow-scheduler python /opt/airflow/scripts/iceberg_count.py $(ARGS)

clean: ## Remove local caches and build artefacts
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache .hypothesis dbt/target dbt/dbt_packages dbt/logs .dbt-local infra/.terraform
