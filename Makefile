# ──────────────────────────────────────────────────────────────────────────────
# Multi-Commodity Quant Forecasting Platform — developer commands
#
# Phase 1 note: most targets are PLACEHOLDERS. They echo intent and exit cleanly
# so the workflow is documented now and wired up in later phases. Replace the
# placeholder bodies as each phase lands (see ARCHITECTURE.md roadmap).
# ──────────────────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help
.PHONY: help test lint typecheck quality db-migrate db-load seed-sources api-dev web-dev etl-run \
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

test: ## Run the pytest suite
	python -m pytest

lint: ## Lint Python with ruff
	python -m ruff check .

typecheck: ## Static type-check with mypy
	python -m mypy -p app

quality: ## Run integration + data-quality gates
	@echo "[quality] placeholder — wire up: pytest tests/integration tests/quality"

db-up: ## Start local PostgreSQL via docker-compose
	$(COMPOSE) up -d postgres

db-down: ## Stop local PostgreSQL
	$(COMPOSE) down

db-migrate: ## Apply database migrations via Alembic (reads DATABASE_URL)
	cd apps/api && python -m alembic upgrade head

db-load: ## Load commodity YAML profiles into the database (idempotent)
	cd apps/api && python -m app.services.profile_loader

seed-sources: ## Seed baseline dim_data_source rows (manual/internal/unknown/seed_profile; idempotent)
	python db/seeds/seed_data_sources.py

api-dev: ## Run the FastAPI dev server
	cd apps/api && python -m uvicorn app.main:app --reload

web-dev: ## Run the Next.js dev server (Phase 9+)
	@echo "[web-dev] placeholder — wire up: (cd apps/web && npm run dev)"

etl-run: ## Real ETL ingestion (later phase). Phase 3A is dry-run only — see `make test`.
	@echo "[etl-run] Phase 3A is a dry-run skeleton (no ingestion). Real connectors land in a later phase."
