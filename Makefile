SHELL := /bin/bash
.DEFAULT_GOAL := help

DBT_ARGS := --project-dir dbt --profiles-dir dbt

.PHONY: help install lint format typecheck test dbt-deps dbt-compile dbt-build check \
	tf-fmt tf-validate compose-config airflow-build up down reset logs backfill iceberg-count clean

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

dbt-compile: dbt-deps ## Compile dbt models against the local DuckDB dev target
	mkdir -p .dbt-local
	uv run dbt compile $(DBT_ARGS) --target dev

dbt-build: dbt-deps ## Seed, run and test the dbt project on the local DuckDB dev target
	mkdir -p .dbt-local
	uv run dbt build $(DBT_ARGS) --target dev

check: lint typecheck test dbt-compile dbt-build ## The gate before every commit

tf-fmt: ## Check Terraform formatting
	terraform -chdir=infra fmt -check -recursive

tf-validate: ## Validate Terraform without a backend
	terraform -chdir=infra init -backend=false -input=false >/dev/null && terraform -chdir=infra validate

compose-config: ## Validate docker-compose.yml
	docker compose config --quiet

airflow-build: ## Build the Airflow image (one image serves every Airflow service)
	docker compose build airflow-webserver

# Builds the image on first use only; run `make airflow-build` after dependency changes.
up: ## Start the local Airflow stack
	mkdir -p .iceberg-local logs/airflow
	docker compose up -d

down: ## Stop the stack, keeping the Postgres metadata volume
	docker compose down --remove-orphans

reset: ## Stop the stack and delete its volumes (fresh Airflow metadata DB on next up)
	docker compose down -v --remove-orphans

logs: ## Tail logs from the stack
	docker compose logs -f --tail=100

backfill: ## Backfill DoltHub history: make backfill START=YYYY-MM-DD END=YYYY-MM-DD [SYMBOLS=SPY,QQQ]
	@if [ -z "$(START)" ] || [ -z "$(END)" ]; then \
		echo "usage: make backfill START=YYYY-MM-DD END=YYYY-MM-DD [SYMBOLS=SPY,QQQ] (no SYMBOLS = watchlist)" >&2; \
		exit 1; \
	fi
	docker compose exec -T airflow-scheduler airflow dags unpause backfill_chains
	symbols=$$(printf '%s' "$(SYMBOLS)" | awk -v RS=, 'NF { printf "%s\"%s\"", sep, $$1; sep = "," }'); \
	docker compose exec -T airflow-scheduler airflow dags trigger backfill_chains \
		--conf "{\"start\":\"$(START)\",\"end\":\"$(END)\",\"symbols\":[$$symbols]}"

iceberg-count: ## Rows per (source, trade_date) in bronze and its content hash; ARGS="--source dolthub"
	docker compose exec -T airflow-scheduler python /opt/airflow/scripts/iceberg_count.py $(ARGS)

clean: ## Remove local caches and build artefacts
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache .hypothesis dbt/target dbt/dbt_packages dbt/logs .dbt-local infra/.terraform
