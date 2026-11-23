# Loop Profile — Multi-Commodity Quant Forecasting Platform

## Project
- App root: repo root · API `apps/api` (`app`) · web `apps/web` · ETL `etl/` · ML `ml/`
- Stack: Python 3.12+ locally / 3.13 in CI (FastAPI, SQLAlchemy, pytest, ruff, mypy) + Next.js 15 / TS / vitest
- Git: yes (`master`); AI commits after gates; push/PR when asked — never `git add -A`
- Baseline (**2026-11-23 Asia/Saigon**, SHA `4853c33`, measured this bootstrap):
  **pytest 620 passed + 1 skipped** · **vitest 78 passed** · ruff 0 · mypy 0 (29 app + 34 etl) ·
  workflows 6/6 · web tsc/eslint/next build clean · **66 profiles** pinned

## Gates (repo root; use `python3` / PATH with tooling)
1. `python3 -m compileall -q etl scripts apps tests ml db apply_views.py`
2. `python3 -m ruff check .`
3. `python3 -m mypy -p app` then `python3 -m mypy etl`
4. `python3 -m pytest` ← ≥ **620** passed, 0 failed (1 PG skip OK if `CQP_TEST_PG_URL` unset)
5. `python3 scripts/ci_check_workflows.py`
6. When `apps/web` touched: `cd apps/web && npm run typecheck && npm test && npm run lint && npm run build`
   ← vitest ≥ **78** green
(`make quality` ≈ 1–5; CI = `.github/workflows/ci.yml`.)

## Runtime smoke (app THẬT — not unit-only)
- Prefer offline: FastAPI `TestClient` + in-memory SQLite (`apps/api/tests/conftest.py`).
- Live local: `make api-dev` → GET `/health`, `/commodities` (expect 66) — **read-only**.
- ETL: `python3 -m etl.ingest` dry-run default; assert plan counts; `--write` needs owner OK.
- Web: `cd apps/web && npm run dev` → `/` + `/stocks`; console clean.
- Network: no prod writes / no outbound secrets in smoke; fixtures for connectors.
- Quirk: if a machine `.env` points at Supabase prod → GET-only forever (this cloud checkout has **no** `.env`).

## Locked invariants
- INV-1 Config-over-code (no commodity hardcode in `etl/`) — `tests/quality/test_etl_contracts.py` + planner twin
- INV-2 No network/creds in core pipeline; connectors + `NETWORK_EXEMPT` — same contract files
- INV-3 Zero look-ahead (`valid_from > T` invisible) — `tests/integration/test_point_in_time_correctness.py`
- INV-4 Inventory **66 profiles** — `test_profiles_quality.py`, `test_schema_and_load.py`, `test_loader.py`, `test_api.py`
  · TODO pin: exact instrument count (YAML entries ≈114; API only asserts `instruments > 0`)
- INV-5 Generic schema (no commodity table names) — `tests/quality/test_schema_contract.py`
- INV-6 Fail-closed API (internal key + forecast guards) — `test_internal_key_gate.py`, `test_forecast_guards.py`, `test_forecast_api_gate.py`
- INV-7 Writes opt-in (ingest/evaluator dry-run; atomic rollback) — `test_ingest_exit_code.py`, `test_forecast_evaluator.py`, `test_etl_writer.py`, `test_etl_rollback.py`
- TODO pin: currency registry↔profile match (waiver list exists) · RLS deny-by-default · alert delivery CAS/idempotency

## Forbidden actions
- No prod DB writes / migrations / seeds / `--write` / Cloud Run deploy / workflow_dispatch without owner OK
- No live network in tests; no secrets in code/logs/commits; never weaken guard tests or lower baselines
- No Telegram/email live send without owner OK; stay in pack Outcome Spec + `CLAUDE.md` phase rules

## Adversarial review
- Method: ≥1 independent verifier/subagent (not the Maker); default REFUTE until concrete failing input
- Mandatory when pack touches INV-1/2/3/6/7, auth, write paths, forecast serving, or money/units
- Lenses: config-over-code · PIT/look-ahead · fail-closed writes/auth · determinism/seeds · currency/units

## Memory
- Location: `.claude/loop-memory.md` (newest on top)
- Format: 1 dense entry/pack — files+contract · INV touched · gate numbers · verdict · verified rules only

## Numeric budgets
- Max fix→re-gate: **3** · Max adversarial fix rounds: **2** · Max smoke retries: **2**

## Verdicts
- Pack: `<PACK>_PASS` | `<PACK>_BLOCKED[_REASON]`
- Gate: `<NAME>_RELEASE_GATE_PASS` | `…_BLOCKED[_BY_…]`

## Known pitfalls (verified)
- Tooling may be user-site `python3 -m …` (ensure `~/.local/bin` on PATH); prefer matching CI 3.13 when possible
- Count tests: measure, never guess — profiles now **66** (PLAN.md §2 text may lag)
- Regenerating `db/views/generated/*` after profile changes is expected
- Quote paths; never `git add -A` (parallel workstreams)
- SQLite tests miss `Numeric(p,s)` rounding — round at write source for PG
