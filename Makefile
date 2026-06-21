# ──────────────────────────────────────────────────────────────────────────────
# Multi-Commodity Quant Forecasting Platform — developer commands
#
# Phase 1 note: most targets are PLACEHOLDERS. They echo intent and exit cleanly
# so the workflow is documented now and wired up in later phases. Replace the
# placeholder bodies as each phase lands (see ARCHITECTURE.md roadmap).
# ──────────────────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help
.PHONY: help test lint typecheck quality db-migrate api-dev web-dev etl-run \
        db-up db-down env

# Allow overriding the compose command (e.g. `make COMPOSE="docker compose" db-up`)
COMPOSE ?= docker compose

help: ## Show this help
	@echo "Multi-Commodity Quant Forecasting Platform — make targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

env: ## Create a local .env from the template if missing
	@test -f .env || cp .env.example .env
	@echo "[env] .env ready (edit it locally; never commit it)"

test: ## Run the pytest suite (etl, ml, integration)
	@echo "[test] placeholder — wire up: pytest etl/tests ml/tests tests/"

lint: ## Lint Python with ruff
	@echo "[lint] placeholder — wire up: ruff check ."

typecheck: ## Static type-check with mypy
	@echo "[typecheck] placeholder — wire up: mypy apps etl ml"

quality: ## Run integration + data-quality gates
	@echo "[quality] placeholder — wire up: pytest tests/integration tests/quality"

db-up: ## Start local PostgreSQL via docker-compose
	$(COMPOSE) up -d postgres

db-down: ## Stop local PostgreSQL
	$(COMPOSE) down

db-migrate: ## Apply SQL migrations in db/migrations (Phase 2+)
	@echo "[db-migrate] placeholder — wire up: apply db/migrations/*.sql"

api-dev: ## Run the FastAPI dev server (Phase 8+)
	@echo "[api-dev] placeholder — wire up: uvicorn apps.api.main:app --reload"

web-dev: ## Run the Next.js dev server (Phase 9+)
	@echo "[web-dev] placeholder — wire up: (cd apps/web && npm run dev)"

etl-run: ## Run the ETL ingestion pipeline (Phase 3+)
	@echo "[etl-run] placeholder — wire up: python -m etl.run"
