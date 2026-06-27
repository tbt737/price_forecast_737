# Phase 8B — guarded OU candidate in the forecast pool

Phase 8A added the OU / damped mean-reversion forecaster as a research-only
candidate (see `phase-8a-ou-research.md`: it improved the best-of on 5/15
commodities — ROBUSTA, INDIAN_CHILIES, COCOA, WHEAT, RICE — with zero regressions).
Phase 8B wires it into the **production** candidate pool, behind the existing safety
gates only.

## What changed (`ml/forecast.py`)

- **OU is one more candidate**, added to the pool alongside `ridge_ar` / `gbm` /
  `gbm_cyc`. It is univariate (no exogenous features) and independent of xgboost, so
  it is available even when gbm is not. It is gated by `enable_ou` (default `OU_ENABLED
  = True`), a config/test hook that removes it cleanly.
- **Selection is unchanged.** The best-of logic was extracted verbatim into a pure,
  unit-testable helper `select_candidate(candidates, naive_mape, margin=SWITCH_MARGIN)`:
  the lowest-MAPE candidate wins, but only displaces the naive benchmark when it clears
  it by the unchanged 2% margin. OU can therefore be chosen **only** when it beats every
  other candidate *and* the naive benchmark by the margin; a weak OU never changes the
  outcome.
- **No candidate was removed or weakened**; the naive benchmark and `SWITCH_MARGIN`
  are untouched. OU is never an unconditional default.

## Metadata

Each horizon's `backtest` block now reports:
- `candidates`: every finite candidate MAPE, including `ou` when enabled, so the
  selected model and OU's standing are both visible.
- `ou_considered`: whether OU was part of the pool for this run.
- `model_used` (already present) records the chosen model — `"ou"` when it wins,
  otherwise the incumbent or `"naive"`.

## Safety

- Pure helper + closed-form model ⇒ deterministic; repeated runs are identical
  (asserted).
- Point-in-time correctness is inherited from Phase 8A (OU fits on the training window
  only; the trailing-mean trend is causal) and the unchanged walk-forward harness.
- No API surface added; no DB writes; no import-time DB/network calls.
- `enable_ou=False` reproduces the pre-8B pool exactly (asserted).

## Tests

- `ml/tests/test_ou_candidate_pool.py` — gating contract (DB-free): OU wins only on
  margin, weak OU is rejected and never changes the outcome, naive holds when nothing
  clears the margin, margin = 2% exactly, disable hook exists and defaults on.
- `tests/integration/test_forecast_ou_pool.py` — with a seeded in-memory price series,
  `ou` appears in the pool metadata and `ou_considered` is `True`; `enable_ou=False`
  removes it; the pool output is deterministic.

## Follow-up (not in scope)

Per-commodity tuning of OU defaults (`trend_span=90`, `trend_damping=0.97`) and a
production-data re-confirmation of the per-commodity win/no-win split remain open. The
gate makes shipping safe in the meantime: OU can only ever help.
