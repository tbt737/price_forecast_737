# Loop Memory — distilled, one entry per pack, newest on top

<!-- Format: ## YYYY-MM-DD <PACK_NAME> — <verdict>
     What shipped (files + contract) · invariants touched · gate numbers · new rules.
     No logs, no transcripts. Prune entries that stop being true. -->

## 2026-07-11 VN30-STOCKS-1 — VN30_STOCKS_1_PASS (prod phase gated, see PLAN §5)
Shipped: 30 VN30 equity profiles (`configs/commodities/<ticker>_vn.yaml`, group `equity`,
basket effective 2026-02-02) + `vn_stocks` connector (`etl/sources/market/vn_stocks.py`,
TradingView-arrays parser, ×1000 VND scale from config, explicit-only like vn_history,
fail-soft incl. url_template.format inside try) + `VnStockSpec` config block + ENTRADE seed
+ ingest.yml 7-day top-up step (inert until prod seed) + web `/stocks` page (group-scoped
`CommodityExplorer` via new `filterByGroup`; home excludes equities; equity chip 📈).
Invariants: INV-1/2 (guards re-registered, NETWORK_EXEMPT ×2), INV-4 bumped to REAL counts
51 profiles/98 instruments (also PLAN §2), INV-6 verified live (401 without key), INV-7
untouched (no prod writes; smoke = isolated SQLite + injected/real fetch, forecast proven
end-to-end: FPT_VN 476 rows → naive fallback, MAPE 3.8%).
Gates: pytest **456+1skip** · vitest **39** · ruff 0 · mypy 0 (28+32) · build ✓ (new baseline).
Adversarial review (2 independent + convergence): fixed url_template crash + NaN/Infinity
filter + 4 guard tests; **open design debt — adjusted-price restatement vs append-only
ingest** (chart API restates history at each corporate action; heal = revision-aware reload
using the existing `revision` grain column) — documented in sources.yaml, follow-up pack
chipped; land it before/with the first prod backfill.
**Rules distilled:** (1) never run `npm run build` while the dev server serves the same
`.next` — it corrupts the dev cache ("Cannot find module './NNN.js'"); restart dev after.
(2) A restating (adjusted) price source is a NEW data class on this platform — check
append-only assumptions before onboarding the next one. (3) Port 3000 may be occupied by
a foreign process — smoke on 3100.

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
