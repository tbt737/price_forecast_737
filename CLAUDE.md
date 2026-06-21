# CLAUDE.md — Operating Rules for AI Agent Sessions

This file governs how any AI coding agent (Claude Code or otherwise) works in this
repository. Read it **first**, every session, before writing code.

The companion documents are `ARCHITECTURE.md` (the system design + 10-phase roadmap)
and `README.md` (setup + commands). This file is the *behavioral contract*.

---

## 1. The prime directive — configuration over code

This is a **generic, configuration-driven multi-commodity platform**.

- **NEVER hardcode business logic for a single commodity.** No `if commodity == "robusta"`.
- All logic is keyed on identifiers: `commodity_id`, `instrument_id`, `region_id`,
  `metric_code`. Names live in YAML profiles (`configs/commodities/`), never in code.
- A new commodity is onboarded by **adding a YAML profile**, not by editing engines.
- If you find yourself typing a commodity's name into a code branch, stop — that
  belongs in a profile.

## 2. Operating rules

1. **Inspect before acting.** Read the current directory structure and any existing
   files (`CLAUDE.md`, `ARCHITECTURE.md`, profiles) before writing. Understand what is
   already there.
2. **No destructive overwrites.** Do not overwrite existing important files without an
   explicit explanation of why and what changes. Preserve research/reference docs.
3. **Security first.** Never hardcode, commit, or print real secrets or credentials.
   `.env` is gitignored; only `.env.example` (blank values) is committed.
4. **Phase isolation.** Work strictly within the scope of the current phase. Do not
   jump ahead to implement business logic, endpoints, or UI before their phase. When a
   phase's definition of done is met, **stop** and report.
5. **Reproducibility.** Anything that affects model output (features, joins, data
   windows) must be deterministic and point-in-time correct (see ARCHITECTURE §3.2).

## 3. Testing principles

- **Tests are not optional for shipped logic.** Every non-trivial module gets tests in
  the matching `*/tests/` directory (`etl/tests`, `ml/tests`, `tests/integration`,
  `tests/quality`).
- **Point-in-time tests guard against look-ahead bias.** Any feature/view that reads
  historical data must have a test proving it cannot see data with `valid_from > T`.
- **Determinism.** Seed every stochastic step; the same inputs must yield the same
  forecast. Backtests must be walk-forward, never random-split.
- **Lint/build passing is NOT proof of correctness.** Run the actual pipeline / start
  the actual service and observe real behavior before declaring something done.
- **Trust but verify generated work.** If a sub-agent or tool reports "all pass,"
  re-run the verification yourself and read the actual numbers before approving.
- Quality gates: `make lint` (ruff), `make typecheck` (mypy), `make test` (pytest),
  `make quality` (the integration + data-quality suite).

## 4. The 3-strike debugging rule

When something fails, do **not** blindly patch symptoms. Follow three strikes:

1. **Diagnose the root cause** using the actual terminal logs / error output.
2. **Apply the smallest, safest fix** that addresses that root cause.
3. **Re-run the command** and confirm.

If the same task fails **3 times**, **STOP**. Do not keep patching. Produce a
**root-cause report**: what was tried, what the logs actually said, and the most
likely underlying cause. Hand control back to the human.

## 5. Conventions

- **Python:** FastAPI + SQLAlchemy + Pydantic; formatted/linted with `ruff`, typed with
  `mypy`. ETL uses pandas/numpy/yfinance/python-dotenv. ML uses scipy (Fourier),
  statsmodels, scikit-learn, xgboost, prophet.
- **Frontend:** React / Next.js + TypeScript; charts via Plotly or ECharts.
- **SQL:** plain SQL migrations in `db/migrations/`; ML reads materialized views in
  `db/views/`, never raw tables.
- **Profiles:** every file in `configs/commodities/` must follow the exact schema in
  `ARCHITECTURE.md` / the existing profiles. Arrays are never left empty.
- **Identifiers:** `snake_case` `commodity_code`s; uppercase exchange `symbol`s.

## 6. Definition of done (per change)

A change is done only when: it stays in phase scope; it follows the configuration-over-code
rule; it has tests (for logic); lint + typecheck + tests pass *and you ran them*; no real
secrets were added; and you have reported what changed and what is intentionally not done.
