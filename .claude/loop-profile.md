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
(`make quality` runs Python gates 1–5 using `python`; CI runs Python and web gates per `.github/workflows/ci.yml`.)

## Runtime smoke (app THẬT — not unit-only)
- Prefer offline: FastAPI `TestClient` + in-memory SQLite (`apps/api/tests/conftest.py`).
- Live smoke, including a local API connected to prod: **GET-only** on `/health` and `/commodities` (expect 66).
- Offline ETL smoke: run the default ingest plan on isolated data with connector fixtures and assert plan counts.
  The default path plans without persisting. Both `--backfill` and `--csv-import` persist even without `--write`.
- Web: `cd apps/web && npm run dev` → `/` + `/stocks`; confirm the browser console is clean.
- Use isolated PostgreSQL for RLS, delivery CAS, migration, and other PostgreSQL-specific tests.
  Set `CQP_TEST_PG_URL` only to a disposable test database.

## Locked invariants
- INV-1 Config-over-code (no commodity hardcode in `etl/`) — `tests/quality/test_etl_contracts.py` + planner twin
- INV-2 No network/creds in core pipeline; connectors + `NETWORK_EXEMPT` — same contract files
- INV-3 Zero look-ahead (`valid_from > T` invisible) — `tests/integration/test_point_in_time_correctness.py`
- INV-4 Inventory **66 profiles and 114 instruments** at the loader boundary —
  `tests/integration/test_schema_and_load.py`; the API instrument check is `instruments > 0`.
- INV-5 Generic schema (no commodity table names) — `tests/quality/test_schema_contract.py`
- INV-6 Fail-closed API (internal key + forecast guards) — `test_internal_key_gate.py`, `test_forecast_guards.py`, `test_forecast_api_gate.py`
- INV-7 Writes opt-in (default ingest/evaluator plan without persisting; ETL writer batch rollback) —
  `test_ingest_exit_code.py`, `test_forecast_evaluator.py`, `test_etl_writer.py`, `test_etl_rollback.py`.
  Treat `--write`, `--backfill`, and `--csv-import` as explicit write modes.

## Invariants to pin
- Currency, unit, and scale stay consistent from the source and profile through storage and serving.
  Check registry↔profile currency against the documented waiver list and test conversions when applicable.
- RLS defaults to deny. Verify allowed and denied operations with the actual app roles on isolated PostgreSQL.
- Alert delivery CAS allows one worker to claim delivery under concurrency. A delivered alert is never sent again.
- Schema changes keep the Alembic and SQL migration paths compatible. Verify affected upgrade paths on isolated PostgreSQL.
- Include concrete evidence for each applicable contract in the pack's Outcome Spec.
  Mark a contract as locked after its corresponding regression test verifies it.

## Forbidden actions
- Prod DB writes, migrations, seeds, `--write`, `--backfill`, `--csv-import`, Cloud Run deploys,
  `workflow_dispatch`, and live Telegram/email sends require explicit owner approval in the session.
- No live network in tests. Keep secrets out of code, logs, and commits. Never weaken a guard test or lower a baseline.
- Stage explicit paths. Never use `git add -A`. Stay within the Outcome Spec and the phase rules in `CLAUDE.md`.

## Adversarial review
- At least one reviewer independent of the Maker receives the [verifier packet](../docs/loop/verifier-packet.md)
  with the complete diff or artifact and evidence at the revision under review.
- Mandatory for INV-1/2/3/6/7, auth, write paths, forecast serving, money/units, RLS, delivery,
  schema/migrations, guard tests, baselines, and the loop profile/templates.
- Ground findings in a failing check or concrete artifact evidence. Unresolved required evidence blocks PASS.
- Review applicable contracts, including config-over-code, point-in-time safety, fail-closed behavior,
  determinism, and currency/unit consistency.

## Memory
- Location: `.claude/loop-memory.md` (newest on top)
- Add one concise entry per pack with the verdict, gate counts, and verified lessons linked to a test or evidence.
  Preserve existing history. Use the [memory template](../docs/loop/memory-distillation.md).

## Numeric budgets
- Max fix→re-gate: **3** · Max adversarial fix rounds: **2** · Max smoke retries: **2**
- Start a pack only after naming it and defining measurable PASS criteria in its
  [Outcome Spec](../docs/loop/outcome-spec-template.md).
- Retry only against a specific gap. Stop at the first PASS, when the same failure recurs without
  new evidence or measurable progress, when fixes oscillate, or when any applicable budget is exhausted.
  If criteria remain unmet, report the blocking evidence.

## Verdicts
- Pack: `<PACK>_PASS` | `<PACK>_BLOCKED[_REASON]`
- Gate: `<NAME>_RELEASE_GATE_PASS` | `…_BLOCKED[_BY_…]`

## Known pitfalls (verified)
- Tooling may be user-site `python3 -m …` (ensure `~/.local/bin` on PATH); prefer matching CI 3.13 when possible
- Count tests: measure, never guess — profiles now **66** (PLAN.md §2 text may lag)
- Regenerating `db/views/generated/*` after profile changes is expected
- Quote paths; never `git add -A` (parallel workstreams)
- SQLite tests miss `Numeric(p,s)` rounding — round at write source for PG
