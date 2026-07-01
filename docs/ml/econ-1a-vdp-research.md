# ECON-1A — Van der Pol candidate: research evaluation (REJECTED)

**Verdict: REJECT — keep research-only, do NOT promote into `ml/forecast.py`.**

## Motivation
An econophysics report proposed modelling price bubbles as a **forced Van der Pol oscillator**
(self-sustaining nonlinear damping → boom-bust limit cycles). This is the *nonlinear*
generalization of the existing `ou` candidate (linear damped mean-reversion). We prototyped it
as a research-only candidate (`ml/models/vdp_forecaster.py`) and evaluated it with the existing
walk-forward harness against the current pool. **Claims require repo evidence — this file is that
evidence.**

## Method (deterministic, point-in-time)
- Slow trend `m_t` = causal trailing mean of log-price; deviation `d_t = log(p_t) − m_t`;
  **normalized** `z_t = d_t / σ_d` so the `(1 − z²)` nonlinearity activates only when the deviation
  exceeds ~1 std (the bubble threshold — in log-space raw deviations are tiny, leaving VdP ≈ linear).
- Fit `z'' = μ(1 − z²)z' − ω² z` by OLS on the causal discrete (velocity, acceleration) of `z`
  (closed-form, no RNG). Guards: require restoring `ω² ∈ (0, 4]`, clamp `|μ| ≤ 5`.
- Forecast by integrating the fitted ODE forward from the anchor state with
  `scipy.integrate.solve_ivp` (RK45, fixed tolerances ⇒ deterministic) + the same damped
  slow-trend drift as OU, anchored to the last price. **Fails closed to flat (= naive)** on short
  history, non-finite log, unstable fit, or any integration blow-up (`|z|>8` or non-finite);
  log-moves clipped to ±0.5.

## Backtest configuration
- Source: **offline** `data/Agriculture_price_dataset.csv` (Agmarknet), national-median daily series
  — DB-FREE. Cyclical Indian produce is the intended VdP test bed (regime evidence: model value
  concentrates in cyclical produce). Futures (GOLD/CORN/…) live only in the DB and were out of this
  offline scope.
- Walk-forward, horizon = 30, folds = 5, `min_train = 180`. Only commodities with enough unique
  daily history qualified (Onion, Potato, Wheat; Tomato/Rice too sparse).
- Selection mirrors production best-of with the 2% `SWITCH_MARGIN` gate.

## Results (MAPE %, lower is better)
| commodity | folds | naive | ridge_ar | gbm | gbm_cyc | ou | **vdp** | best-of | +ou | **+vdp** |
|---|---|---|---|---|---|---|---|---|---|---|
| Onion | 5 | 20.63 | 28.34 | 29.71 | 30.83 | 24.48 | **26.05** | naive | naive | naive |
| Potato | 5 | 12.46 | 13.10 | 12.38 | 13.82 | 15.02 | **25.01** | naive | naive | naive |
| Wheat | 5 | 1.47 | 2.42 | 2.16 | 2.16 | 1.05 | **2.30** | naive | ou | ou |

**Summary (3 commodities, h=30):** vdp beats naive **0/3** · pool+vdp beats pool **0/3** ·
catastrophic (vdp > 2× naive) **1/3** (Potato).

## Findings
- **Does it beat naive?** No — VdP is worse than naive on all three series.
- **Does it beat the current pool?** No — under the 2% gate the `+vdp` column never chooses `vdp`;
  adding VdP changes nothing (on Wheat the pool already picks `ou`, which legitimately beats naive
  1.05 < 1.47 — confirming the harness works and OU remains the better mean-reversion candidate).
- **Catastrophic regression:** Potato — the forward-integrated oscillator overshoots (extrapolates a
  swing that doesn't materialize), producing ~2× the naive error even after the ±0.5 log clip.
- Consistent with the platform's prior evidence that added model complexity rarely beats naive on
  these series (regime-gate and meta-blend were also rejected).

## Recommendation
**REJECT.** Retain the code as a research-only candidate (not imported by production) plus this note.
Do not promote to `ml/forecast.py`; the production pool and 2% gate are unchanged. The nonlinear
oscillator hypothesis did not survive walk-forward evidence; deeper econophysics ideas
(PINN/MARL/TaylorNet) should not be pursued on the strength of the report alone.
