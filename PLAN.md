# PLAN.md — Source of Truth (kế hoạch dự án)

> Authoritative entry point for planning. Read together with `CLAUDE.md` (behavioral
> contract), `ARCHITECTURE.md` (system design; §5 = the completed ten-phase roadmap) and
> `.claude/loop-profile.md` (how every pack runs). Update this file whenever a workstream
> changes state; do not let plans live only in chat/memory.

## 1. Project status snapshot

- The ten-phase roadmap (`ARCHITECTURE.md` §5) is **complete**: ETL (dry-run-first write
  path, provenance, connector gate), zero-lookahead feature views, walk-forward backtests,
  model registry, FastAPI backend, Next.js UI.
- Platform is **LIVE in production**: Cloud Run (`cqp-api`, `cqp-web`) + Supabase Postgres
  (deny-by-default RLS). Real CI gate runs on every push/PR (`.github/workflows/ci.yml`).
- Self-improving loop is bootstrapped: `.claude/loop-profile.md` + `.claude/loop-memory.md`
  (commits `a45695e`, `4682605`). Đợt-1 hardening, OPS-CLEAN-1, ETL-VN-3/4, ML-FIX-1
  (deployed) and ACC scheduling (`4925b9d`) are DONE.

## 2. Production baseline

Locked 2026-07-07 at commit `4925b9d` (details + monotonic rule in `.claude/loop-profile.md`):
**pytest 409 passed + 1 skipped** (PG-only) · **web vitest 34 passed** · ruff 0 · mypy 0 ·
**20 commodity profiles** (pinned by `tests/quality/test_profiles_quality.py`). Test counts
never go down; locked invariants never weaken.

> Current (2026-07-11, pack VN30-STOCKS-1): **pytest 456 + 1 skipped · vitest 39 · 51
> profiles / 98 instruments** (21 commodities + 30 VN30 equities, `commodity_group: equity`).

> ⚠️ Stale companion docs: `README.md` still says "16 profiles" and `ARCHITECTURE.md`'s
> status header still says "18 profiles / Phases 1–9 / cloud hosting pending — see DEPLOY.md".
> Those predate production. **This file supersedes them for current status** — in particular,
> do NOT follow ARCHITECTURE's "go live" pointer; deploys need explicit approval (§11).

## 3. Active priorities

No code pack is currently in flight. Highest-value next actions, in order:
1. The two **manual-only GitHub tasks** (§4) — they close the last Đợt-1 gaps.
2. **ACC-REVIEW** when its artifact exists (§5) — first real evidence of live forecast skill.
3. If idle capacity remains: deferred polish (§6) as a small tooling pack.

## 4. Manual-only tasks (owner, GitHub UI — sessions have no gh auth)

- [ ] Verify/enable **branch protection** on `master` requiring the checks
  `Python (lint + tests)` and `Web (lint + test + build)` (exact display names from
  `ci.yml` — short names like "Python" will not bind), then open one intentionally
  failing PR to confirm the gate actually blocks merge.
- [ ] **Dispatch `vn-freshness-monitor.yml` once** (Actions → run workflow) to smoke-test the
  live read-only VN monitor (cron 01:30 UTC).

## 5. Waiting workstreams (do not execute yet)

- **VN30-PROD (production phase of VN30-STOCKS-1) — WAITING on user approval.** The 30
  VN30 equity profiles + `vn_stocks` connector + `/stocks` page shipped code-complete
  (2026-07-11); production still needs, in order: (1) profile load (`make db-load` against
  the Supabase pooler URL), (2) `seed_ingestion_sources` (auto-runs with ingest),
  (3) one deep backfill `python -m etl.ingest --backfill --sources vn_stocks
  --history-days 5400`, (4) Cloud Run redeploy of cqp-api + cqp-web. ⚠ Before or shortly
  after (3), land the **adjusted-price restatement heal** pack (see the vn_stocks caveat
  in `configs/ingestion/sources.yaml`): the chart API restates history at each corporate
  action while ingest is append-only — plan = revision-aware reload using the existing
  `revision` grain column. The daily workflow step is already in `ingest.yml` and is inert
  until (1) happens. VN30 basket = review effective 2026-02-02; refresh on each
  semiannual HOSE review.
- **ACC-REVIEW — WAITING.** The accuracy loop is scheduled (`4925b9d`): writer logs pending
  forecasts to `fact_forecast_log` after each ingest; evaluator (Mondays 03:00 UTC) matures
  rows once `target_date <= today`. Writer started 2026-07-05, so no matured rows exist yet.
  Trigger condition: `fact_forecast_log` contains evaluated (non-pending) rows — check per
  `docs/ml/accuracy-loop-runbook.md` §"Reading the results". Never fabricate evaluator
  results; until the artifact exists this stays WAITING, not a TODO to run now.

## 6. Deferred polish (small, safe, anytime)

- Migrate `next lint` → ESLint CLI (deprecated in Next 16).
- Silence the multiple-lockfiles workspace-root warning via `outputFileTracingRoot`.
- Optional whitespace gate in CI.
- Refresh stale docs: `README.md` profile count (16→20) and `ARCHITECTURE.md` status header
  (18 profiles / "cloud hosting pending" → current production reality; see §2 note).

## 7. Locked / approval-required work

- **Skills Loop optimizer** — LOCKED pending explicit user approval (duyệt-trước-khi-làm).
  Branch `feature/skills-loop-scoring-lab` is local-only: never merge/push/touch it in a
  pack without that approval. Scope confined to `docs/skills-loop/`, `skills/`,
  `scripts/skills_loop/`, `tests/skills_loop/`.
- **RESEARCH-PUBLISH-1** (optional) — publish sanitized research docs; repo is public, so
  this needs an explicit user decision on IP first.

## 8. Inactive / rejected research tracks (do not retry without new evidence)

- **ECON-1A Van der Pol — REJECTED by evidence** (`ef06068`): beats naive 0/3, catastrophic
  on Potato; research-only, guarded by `test_vdp_forecaster.py::test_not_wired_into_production`.
- **Volatility regime-gate — REFUTED** (model value concentrates in cyclical produce and
  grows with volatility).
- PINN / MARL / deep TaylorNet / fractional derivatives — deferred, research-grade.
- **ECON-3 CVaR confidence bands (display-only)** is the preferred candidate IF econophysics
  is revisited — behind ACC/VN priorities; backtest by calibration coverage, not vs naive.

## 9. No-action monitoring items

- **GOLD_VN** (`VNAPPMOB_SJC_1L`): ~123/252 rows, self-accumulating daily (22:00 UTC ingest
  + self-heal top-up) toward MIN_HISTORY=252 — months away; nothing to do but wait.
- VN freshness monitor (01:30 UTC) turns its workflow red on staleness — watch, don't touch.
- CI gate runs itself on every push/PR.

## 10. Pack selection rules

- Every substantial change runs as a **pack** per `.claude/loop-profile.md` — Step 0 is
  always reading that profile. User triggers with "chạy pack <tên>" / "chạy release gate".
- Selection order: production safety > data reliability > accuracy evidence > polish.
- WAITING items (§5) need their artifact to exist first; LOCKED items (§7) need explicit
  user approval; manual-only items (§4) cannot be automated from sessions.
- Docs-only packs still run the full loop (spec → gates → adversarial review → distill).

## 11. Release safety rules (summary — full text in `.claude/loop-profile.md`)

- Local `.env` points at the **live Supabase DB**: local smoke is GET/read-only; every write
  path (`etl.ingest --write`, evaluator `--write`, migrations, seeds, deploys) requires
  explicit user approval in-session.
- No push/merge/tag unless asked; stage explicit paths, never `git add -A`.
- Baselines are monotonic; never weaken a guard test to get green.
- Every pack ends with a verdict + one distilled entry in `.claude/loop-memory.md`.
