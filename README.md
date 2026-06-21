# Multi-Commodity Quant Forecasting Platform

A **generic, configuration-driven** AI platform for forecasting commodity prices across
**agriculture, energy, and metals**, plus macro/logistics indicators. New commodities
are onboarded by adding a YAML profile — **never** by hardcoding business logic.

> **Project status: Phase 1 — Foundation Initialization.** This repository currently
> contains the monorepo skeleton, architectural docs, configuration scaffolds, and 16
> commodity profiles. No ETL, ML, API, or UI logic is implemented yet. See
> `ARCHITECTURE.md` for the full 10-phase roadmap.

---

## Core idea

Everything is keyed on identifiers — `commodity_id`, `instrument_id`, `region_id`,
`metric_code` — and described declaratively in `configs/commodities/*.yaml`. The same
engine forecasts robusta coffee and gold because both are just *instruments + regions
+ drivers + data sources* in YAML.

## Tech stack

| Layer        | Technology                                                              |
| ------------ | ---------------------------------------------------------------------- |
| Database     | PostgreSQL, SQL migrations, materialized views for ML                  |
| Backend      | FastAPI, SQLAlchemy, Pydantic, REST                                    |
| ETL          | Python, pandas, numpy, yfinance, python-dotenv                        |
| Machine Learning | scipy (Fourier), statsmodels, scikit-learn, xgboost, prophet      |
| Frontend     | React / Next.js, TypeScript, Plotly / ECharts                         |
| Infra/Test   | pytest, ruff, mypy, Docker Compose, Makefile                          |

## Repository layout

```
.
├── CLAUDE.md            # Operating rules for AI agent sessions (read first)
├── ARCHITECTURE.md      # System design, DB schema, look-ahead handling, roadmap
├── README.md            # This file
├── .env.example         # Blank environment template (copy to .env)
├── Makefile             # Standard developer commands
├── docker-compose.yml   # Local PostgreSQL
├── apps/
│   ├── api/             # FastAPI service (Phase 8)
│   └── web/             # Next.js frontend (Phase 9)
├── db/
│   ├── migrations/      # SQL schema migrations (Phase 2)
│   ├── views/           # ML-facing materialized views (Phase 5)
│   ├── seeds/           # Reference/dimension seed data
│   └── commodity_profiles/  # DB-side mirror of commodity profiles
├── etl/
│   ├── sources/{market,weather,macro,logistics,supply_demand,events}/
│   ├── loaders/         # Normalize raw → observation rows
│   └── tests/
├── ml/
│   ├── features/        # Feature engineering (Fourier, lags, rolling)
│   ├── models/          # Model families behind one interface
│   ├── backtests/       # Walk-forward backtesting
│   ├── registry/        # Versioned model metadata
│   └── tests/
├── configs/commodities/ # 16 YAML commodity profiles (source of truth)
├── data/{raw,processed,exports}/   # Local data artifacts (gitignored)
├── infra/{docker,github-actions,deployment}/
└── tests/{integration,quality}/
```

## Getting started (local)

> Phase 1 only scaffolds the project. The commands below describe the intended
> workflow; most targets are placeholders until later phases land.

```bash
# 1. Configure environment
cp .env.example .env        # then fill in values locally (never commit .env)

# 2. Start local PostgreSQL
docker compose up -d postgres

# 3. Developer workflow (placeholders today)
make help                   # list available targets
make db-migrate             # apply SQL migrations            (Phase 2+)
make etl-run                # run ETL ingestion               (Phase 3+)
make api-dev                # run FastAPI dev server          (Phase 8+)
make web-dev                # run Next.js dev server          (Phase 9+)

# 4. Quality gates
make lint                   # ruff
make typecheck              # mypy
make test                   # pytest
make quality                # integration + data-quality suite
```

## Commodity profiles

The 16 profiles in `configs/commodities/` span agriculture, metals, energy, and
logistics — including specialty agri trades (chinese garlic, indian chilies, red onion
India/China, peanuts) and the `freight_indices` logistics driver set. Each profile
follows the strict schema documented in `ARCHITECTURE.md` and `CLAUDE.md`.

## Contributing / agent sessions

Read **`CLAUDE.md`** before making changes. Key rules: configuration over code, inspect
before acting, no destructive overwrites, security first, stay in phase scope, and the
3-strike debugging rule.

## Security

No real secrets live in this repo. `.env` is gitignored; only `.env.example` with blank
values is committed. Never print or commit credentials.
