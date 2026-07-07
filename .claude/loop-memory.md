# Loop Memory — distilled, one entry per pack, newest on top

<!-- Format: ## YYYY-MM-DD <PACK_NAME> — <verdict>
     What shipped (files + contract) · invariants touched · gate numbers · new rules.
     No logs, no transcripts. Prune entries that stop being true. -->

## 2026-07-07 PLAN-SOT — PLAN_SOURCE_OF_TRUTH_BOOTSTRAP_PASS
Docs-only pack: created root `PLAN.md` (11 sections; authoritative planning entry point;
ACC-REVIEW recorded WAITING on first matured `fact_forecast_log` rows). Adversarial review
(2 independent reviewers) caught a wrong golden number: repo has **20** commodity profiles
(test-pinned), not 16 — fixed in PLAN.md + this profile's baseline/INV-4 + entry below.
**Rules distilled:** (1) seed golden numbers from the pinning TEST, never from README/docs —
`README.md` (16) and `ARCHITECTURE.md` header (18, "cloud hosting pending") are stale; PLAN.md
§2 note supersedes them. (2) Branch-protection checks must use full display names
`Python (lint + tests)` / `Web (lint + test + build)`. Gates: structure-check ALL PASS,
`git diff --check` clean, pytest untouched (docs-only).

## 2026-07-07 BOOTSTRAP — LOOP_BOOTSTRAP_PASS
Created `.claude/loop-profile.md` (gates, 7 locked invariants, smoke method, budgets) and this
memory file. Baseline locked at commit 4925b9d: pytest **409 passed + 1 skipped**, web vitest
**34 passed**, ruff clean, mypy clean (28 app + 31 etl files), 20 commodity profiles
(bootstrap entry originally said 16 — corrected by PLAN-SOT review). Verified
facts distilled into the profile: dev toolchain is global Python 3.13 (not `.venv`); local
`.env` points at the live Supabase DB, so smoke is GET-only and every write path stays dry-run.
