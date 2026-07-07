# Loop Profile — Multi-Commodity Quant Forecasting Platform

## Project
- App root: repo root (API = `apps/api` as package `app`; web = `apps/web`; ETL = `etl/`; ML = `ml/`)
- Stack: Python 3.13 global toolchain (FastAPI + SQLAlchemy + pandas + statsmodels/xgboost;
  pytest 9 / ruff / mypy) + Next.js + TS + vitest in `apps/web`
- Git: yes (branch `master`; AI sessions commit only after gates pass, push/tag only when asked)
- Baseline (2026-07-07, commit 4925b9d): **pytest 409 passed + 1 skipped** (PG-only, needs
  `CQP_TEST_PG_URL`) · **web vitest 34 passed** · ruff 0 · mypy 0 (28+31 files) · 20 profiles

## Gates (run from repo root with GLOBAL `python`, not `.venv` — see pitfalls)
1. `python -m compileall -q etl scripts apps tests ml db apply_views.py`
2. `python -m ruff check .`
3. `python -m mypy -p app` then `python -m mypy etl`
4. `python -m pytest`            ← must stay ≥ 409 passed, 0 failed (the 1 PG skip is OK)
5. `python scripts/ci_check_workflows.py`
6. Only when `apps/web` touched: `npm test && npm run lint && npm run build` in `apps/web`
   ← must stay ≥ 34 tests green
(`make quality` mirrors 1+2+4+5; CI = `.github/workflows/ci.yml` runs the same.)

## Runtime smoke (sim-to-real)
- ⚠️ Local `.env` `DATABASE_URL` points at the **LIVE Supabase production DB**
  (`db.odjtptcfptufbeculmbt.supabase.co`). All local smoke is **GET/read-only**.
- API: `make api-dev` (uvicorn :8000) → hit `/health`, `/commodities`, `/forecast/...` GETs;
  assert HTTP codes + response shape; watch the uvicorn console for tracebacks.
- ETL: `python -m etl.ingest` is **dry-run by default** — smoke with dry-run and read the
  plan counts; `--write` against prod is forbidden without explicit user approval.
- Evaluator: `python scripts/evaluate_forecast_log.py` (also dry-run by default).
- Web: `cd apps/web && npm run dev` → load dashboard, check browser/console errors.
- Offline deterministic alternative: FastAPI `TestClient` + in-memory SQLite exactly as in
  `apps/api/tests/conftest.py`.

## Locked invariants
- INV-1 **Config-over-code**: no commodity token (`robusta`,`gold`,… whole-word) anywhere in
  `etl/` code incl. comments — pinned by `tests/quality/test_etl_contracts.py::test_etl_code_is_generic*`
  + twin in `test_etl_planner_contract.py`
- INV-2 **No network/credentials in core pipeline**; connectors are the sanctioned boundary,
  registered in `NETWORK_EXEMPT` in BOTH contract files — pinned by
  `…::test_core_pipeline_needs_no_network*`
- INV-3 **Zero look-ahead**: features/views never see data with `valid_from > T` — pinned by
  `tests/integration/test_point_in_time_correctness.py`
- INV-4 **Inventory counts** (20 profiles + instrument/commodity counts) — pinned by
  `tests/quality/test_profiles_quality.py`, `tests/integration/test_schema_and_load.py`,
  `apps/api/tests/test_loader.py`, `apps/api/tests/test_api.py`
- INV-5 **Generic schema**: table names never hardcode a commodity — pinned by
  `tests/quality/test_schema_contract.py`
- INV-6 **Fail-closed API**: internal/mutating endpoints gated by internal key; forecast params
  bounded — pinned by `apps/api/tests/test_internal_key_gate.py`, `test_forecast_guards.py`,
  `tests/integration/test_forecast_api_gate.py`
- INV-7 **Writes are opt-in**: ingest + evaluator default to dry-run; batch writes are atomic
  w/ rollback — pinned by `tests/quality/test_ingest_exit_code.py`, `test_forecast_evaluator.py`,
  `tests/integration/test_etl_writer.py`, `test_etl_rollback.py`

## Forbidden actions
- No writes, migrations, seeds, or `--write` runs against the live Supabase DB; no Cloud Run
  deploys; no GitHub workflow dispatch — without explicit user approval in this session.
- No live network in tests — connectors are tested via captured fixtures with injected `fetch`.
- No secrets in code/logs/commits; `.env` stays uncommitted; only `.env.example` (blank) moves.
- Never `git add -A` (parallel workstreams live in this tree) — stage files explicitly.
- Never weaken/delete a guard test or lower a baseline count to get green.
- Stay in phase scope per `CLAUDE.md`; 3-strike debugging rule applies.

## Adversarial review
- Method: spawn ≥2 fresh reviewer subagents (Agent tool) that did not write the code; give each
  the diff + outcome spec only. Each raw finding then goes to a skeptic subagent whose default
  verdict is REFUTED (must produce a concrete failing input to confirm). A multi-agent Workflow
  is used only if the user opts in (e.g. "ultracode").
- Lenses that matter here: config-over-code/generic-ness · look-ahead & point-in-time safety ·
  fail-closed writes & API auth · determinism/seeding of stochastic steps.

## Memory
- Location: `.claude/loop-memory.md` (in-repo, newest entry on top)
- Format: one dense entry per pack — what shipped (files + contract), invariants touched,
  gate numbers (new baseline), verdict, newly distilled rules. No logs/transcripts.

## Numeric budgets
- Max fix→re-gate cycles per pack: 3
- Max adversarial-review fix rounds: 2
- Max runtime-smoke retries: 2 (then report, don't thrash)

## Verdicts
- Pack: `<PACK_NAME>_PASS` / `<PACK_NAME>_BLOCKED[_<REASON>]`
- Release gate: `<GATE_NAME>_RELEASE_GATE_PASS` / `…_BLOCKED[_BY_<REASON>]`

## Known pitfalls (verified)
- Dev tools live on the **global** Python 3.13, not `.venv` (venv has runtime deps only) —
  running `.venv/Scripts/python -m ruff|mypy` fails with "No module named".
- Local `.env` → production Supabase (see smoke section). Tests never touch it (in-memory
  SQLite); `tests/integration/test_daily_conflicts.py` skips unless `CQP_TEST_PG_URL` is set.
- Count tests (INV-4): run the suite and read the real numbers — never guess counts.
- `db/views/generated/010_mv_ml_daily_features_wide.sql` auto-regenerates when profiles change;
  the regenerated diff is expected — keep it.
- Repo path contains Vietnamese diacritics — always quote paths; some tools garble the name in
  output (cosmetic only).
- `git diff` shows nothing for untracked files — to review NEW files before commit use
  `git add -N <files> && git diff -- <files>`, or stage then `git diff --cached -- <files>`.
