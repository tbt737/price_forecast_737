# Loop Memory — distilled, one entry per pack, newest on top

<!-- Format: ## YYYY-MM-DD <PACK_NAME> — <verdict>
     What shipped (files + contract) · invariants touched · gate numbers · new rules.
     No logs, no transcripts. Prune entries that stop being true. -->

## 2026-07-07 BOOTSTRAP — LOOP_BOOTSTRAP_PASS
Created `.claude/loop-profile.md` (gates, 7 locked invariants, smoke method, budgets) and this
memory file. Baseline locked at commit 4925b9d: pytest **409 passed + 1 skipped**, web vitest
**34 passed**, ruff clean, mypy clean (28 app + 31 etl files), 16 commodity profiles. Verified
facts distilled into the profile: dev toolchain is global Python 3.13 (not `.venv`); local
`.env` points at the live Supabase DB, so smoke is GET-only and every write path stays dry-run.
