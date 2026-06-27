# Rejected forecast-ensemble experiments

This note records forecasting ideas that were **tested and rejected** on out-of-sample
evidence, so they are not silently re-attempted. Both came from the "Dual Physics
Ensemble" (Newton + RLC + Meta-Learner) research report. The report's one *accepted*
idea — the RLC restoring force, implemented as the OU / mean-reversion candidate — is
live (Phase 8A research → Phase 8B gated into the pool). See
`phase-8a-ou-research.md` and `phase-8b-ou-integration.md`.

**Accepted production policy (unchanged):** a per-commodity, per-horizon walk-forward
selects the lowest-MAPE candidate from `{ridge_ar, gbm, gbm_cyc, ou}`, but only
displaces the **naive** random-walk benchmark when it beats it by the **2% margin**
(`SWITCH_MARGIN`). Hard best-of, not a gate or a blend.

---

## 1. Volatility regime gate — REJECTED

**Hypothesis (report's damping-ratio / regime idea):** the model loses to naive in
volatile/disrupted regimes and should gate toward naive when realized volatility is
high.

**Test:** dense rolling-origin walk-forward (Ridge AR, horizon 30, ~400–590 folds per
commodity), each fold labelled calm vs volatile by `vol_20` split at each commodity's
median. Edge = `naive_MAPE − model_MAPE` (positive = model beats naive).

**Evidence that rejected it:** the model edge did **not** collapse in volatility — it
was *larger* when volatile. Mean edge: calm **+0.26** vs volatile **+0.48**. The
cyclical produce (INDIAN_CHILIES +1.87→+4.25, ROBUSTA +0.96→+3.17) gained the *most*
in volatile windows. A gate that leans toward naive in turbulence would discard real
signal. The true axis is commodity *liquidity/type* (liquid futures ≈ random walk;
cyclical produce has exploitable structure), which the existing best-of already
handles per-commodity.

## 2. Out-of-fold weighted meta-learner / blend — REJECTED

**Hypothesis (report's "Lõi 3 Meta-Learner"):** an out-of-fold weighted blend of the
trend engine (Ridge AR) and the reversion engine (OU) beats hard best-of selection.

**Test:** out-of-fold inverse-MAPE blend of `{ridge_ar, ou}` (weights from past folds
only — no look-ahead), horizon 30, across all 15 commodities, vs the production
best-of rule.

**Evidence that rejected it:**

| Strategy | Mean MAPE (15 commodities) |
|---|---|
| **best-of (production)** | **8.176** |
| meta-learner blend | 8.336 (worse) |

The blend "won" on 10/15 commodities but only at **noise level** (≤0.33 MAPE), while it
**lost badly** on produce where one engine is weak — **CHINESE_GARLIC −1.76**,
**RED_ONION_INDIA −1.60** — because a weighted blend always keeps a fraction of the
bad engine, whereas best-of discards it entirely. For this heterogeneous commodity
set, hard selection is both more accurate on average and more robust.

---

## Decision & warning

- **Keep best-of + naive 2% margin.** Do **not** build a volatility regime gate or a
  meta-learner/weighted blend.
- **Do not reintroduce** either idea without **new out-of-sample evidence** that
  reverses the findings above — e.g. a materially different commodity universe, a new
  exogenous data source that changes the per-regime edge, or a blend variant that
  provably avoids the produce regressions on a fresh walk-forward. Re-run the scratchpad
  experiments (`regime_slice_eval.py`, `meta_blend_eval.py` patterns) and read the
  actual numbers before any such change.
- Exogenous features (FX, weather, freight) were separately found not to help and are
  not wired into the model.
