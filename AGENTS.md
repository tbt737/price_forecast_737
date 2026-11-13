# AGENTS.md

Behavioral rules for this repo live in `CLAUDE.md` (read it first). Planning/status is in
`PLAN.md`; design in `ARCHITECTURE.md`; standard dev commands in `README.md` and the
`Makefile`.

## Cursor Cloud specific instructions

Durable, non-obvious notes for running this platform inside the Cursor Cloud VM. Standard
commands are documented in the `Makefile` / `README.md` — this section only records the
gotchas that are not obvious from those files.

### Services and ports

| Service | Command (from repo root) | Port |
| --- | --- | --- |
| PostgreSQL | `sudo docker compose up -d postgres` | host **5432** |
| FastAPI API | `cd apps/api && python -m uvicorn app.main:app --reload` (`make api-dev`) | 8000 |
| Next.js web | `cd apps/web && npm run dev` (`make web-dev`) | 3000 |

### Python runs inside a virtualenv (`.venv`)

- Python deps are installed into `/workspace/.venv` (the base image only ships `python3`,
  there is **no** system `python`). **Activate it first** — `source .venv/bin/activate` —
  so the `Makefile`/`README` commands (`python -m pytest`, `ruff`, `mypy`, `alembic`,
  `uvicorn`, `etl.ingest`, `apply_views.py`) resolve. The startup update script recreates
  `.venv` and installs `requirements-dev.txt`.
- Running scripts from `apps/api/` fails with `ModuleNotFoundError: No module named 'ml'`.
  Run repo-wide scripts from `/workspace` (pytest is configured with
  `pythonpath = ["apps/api", "."]`); for ad-hoc scripts use
  `PYTHONPATH=apps/api:. python ...`.

### Docker daemon is NOT auto-started

- Docker is installed but the daemon does not start on boot. Start it once per session
  (it must keep running), e.g. in a tmux window: `sudo dockerd`. All `docker` /
  `docker compose` commands need `sudo` because the daemon runs as root.
- The daemon is pre-configured for this nested VM via `/etc/docker/daemon.json`
  (`fuse-overlayfs` storage driver + `containerd-snapshotter` disabled — both required for
  Docker 29 + fuse-overlayfs here). Do not remove that config.

### Local `.env` points at the LOCAL Postgres (not Supabase)

- `PLAN.md` assumes local `.env` targets the live Supabase DB. In this VM the `.env`
  instead targets the **local dockerized Postgres**, so local writes (`etl.ingest --write`,
  migrations, MV refresh) are safe and expected — they hit the throwaway local DB.
- `.env` is gitignored, so it is not in the repo. If it is missing, recreate it from
  `.env.example` with these dev values (no real secrets):
  - `DATABASE_URL=postgresql+psycopg://cqp:cqp_local_dev@localhost:5432/commodity_quant`
    (plus the matching `POSTGRES_DB=commodity_quant`, `POSTGRES_USER=cqp`,
    `POSTGRES_PASSWORD=cqp_local_dev`, `POSTGRES_PORT=5432`)
  - `INTERNAL_API_KEY=local-dev-internal-key` — the always-on `GET /forecast` returns 503
    when this is unset and 401 when a caller omits the `X-Internal-Key` header.
  - `ENABLE_ML_FORECAST_API=true` and `ENABLE_ML_MODELS_API=true` — the `POST /forecast`
    and `/models` endpoints are OFF by default and only mounted when these are set.
- The compose file maps host **5432** here (its built-in default is 5433) because `.env`
  sets `POSTGRES_PORT=5432`. Keep `DATABASE_URL` on the same port.

### First-time DB bring-up (one-off per fresh database)

Run from `/workspace` with `.venv` active and Postgres up:
`make db-migrate` → `make db-load` → `make seed-sources` →
`python -m etl.ingest --write --sources prices --period 2y` (ETL needs network — Yahoo
Finance) → `python apply_views.py --apply`.

### Forecasts need history + a populated materialized view

- A forecast requires ≥252 trading days of `fact_price_daily` history **and** the ML
  materialized view `mv_ml_daily_features_wide`. After ingest, the view must be refreshed.
- Gotcha: the **first** refresh must be non-concurrent —
  `REFRESH MATERIALIZED VIEW mv_ml_daily_features_wide` — because
  `scripts/refresh_ml_features.py --write` uses `REFRESH ... CONCURRENTLY`, which errors on
  a never-populated view. Subsequent refreshes can use the script.
- After that, `POST /forecast {"commodity_code":"GOLD","horizon_days":30}` returns a full
  forecast (e.g. GOLD/COPPER/CRUDE_OIL each carry ~504 sessions from a 2y ingest).

### Known non-environment test failure

- `tests/quality/test_weekly_movers.py::test_main_exit_codes` fails purely because it is
  wall-clock-dependent: its fixture pins `last_date=2026-07-21` and the freshness gate
  refuses to send once "today" is more than 3 trading days later. This is not a
  dependency/setup problem; the rest of the suite passes.
