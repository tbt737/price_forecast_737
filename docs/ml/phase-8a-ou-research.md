# Phase 8A — OU / damped mean-reversion forecaster (research)

**Status: research candidate, NOT enabled as a production default.** This phase
adds a transparent mean-reversion forecaster, evaluates it by walk-forward against
the existing candidates, and records the evidence. Wiring it into the production
best-of pool (`ml/forecast.py`) is a separate, explicitly-approved follow-up.

## Motivation

The deep-research "Dual Physics Ensemble" report attributes short-run dynamics to
an RLC engine whose **restoring force** pulls price back toward an equilibrium. A
prior regime-slice experiment refuted a volatility *gate* (the model does not
collapse in turbulence — for cyclical produce it gets *better*), but it confirmed
that **mean-reversion is the value driver for cyclical produce** (chilli, robusta,
onion). Phase 8A captures exactly that one mechanism — the restoring force — as a
deterministic, point-in-time, univariate candidate. No new data, no metaphor-gate.

## Formula

For log-price `p_t`:

- **Slow trend** `m_t` = causal trailing mean of `p` over `trend_span` (point-in-time;
  uses only `p[t-span+1 .. t]`).
- **Deviation** `d_t = p_t - m_t`.
- **Reversion persistence** `phi ∈ [0, 0.999]` estimated by OLS-through-origin of
  `d_{t+1}` on `d_t` over the training window (`kappa = 1 - phi` is the discrete OU /
  AR(1) mean-reversion speed). The deviation decays geometrically: `d_{t+k} = phi^k · d_t`.
- **Damped slow-trend drift** `g` (per step), continued with Gardner damping so a
  steep recent slope cannot extrapolate without bound:
  `S_k = Σ_{j=1..k} damping^{j-1}` (saturates when `damping < 1`).

Anchored forecast `k` steps ahead (relative to the last price `y_anchor`):

```
Δ_k   = g · S_k  +  (phi^k − 1) · d_anchor
ŷ_k   = y_anchor · exp(Δ_k)
```

`(phi^k − 1) · d_anchor` is the restoring force: if price is above trend
(`d_anchor > 0`) it is negative ⇒ pulls price down toward the trend, and vice versa.
Defaults: `trend_span=90`, `trend_damping=0.97`, `drift_lookback=60`.

## Point-in-time / leakage safety

- The trailing mean is causal (prefix-sum, never reads future indices); a unit test
  mangles all data after index *i* and asserts `m[:i+1]` is unchanged.
- `fit(..., end=cut)` estimates `phi`, `g`, `σ` from `logy[:cut]` only; mangling
  `logy[cut:]` leaves `phi_`/`g_` unchanged (tested).
- `forecast` reads only `logy[:anchor_idx+1]`; mangling later values does not change
  the forecast (tested).
- Walk-forward (`walk_forward_ou`) reuses the existing rolling-origin harness, so each
  fold trains only on its past slice and the naive benchmark is computed identically.

## Fail-closed behaviour

OU returns a flat (= naive) forecast when: history `< trend_span + horizon + 5`, or the
log-price window is non-finite (a non-positive price upstream ⇒ `log` is non-finite ⇒
rejected). Closed form ⇒ bit-for-bit deterministic; no RNG, no DB/network, no input
mutation. All asserted by `ml/tests/test_ou_forecaster.py` (12 tests).

## Walk-forward evaluation (horizon 30d, 6 folds, read-only real data)

Edge = `naive_MAPE − model_MAPE` (positive ⇒ beats naive). `best_of` mirrors the
production rule (lowest MAPE, but only leaves naive when cleared by the 2% margin).

| commodity | group | naive | ridge | gbm | gbm_cyc | OU | best_of (edge) | **best_of+OU (edge)** |
|---|---|---|---|---|---|---|---|---|
| ROBUSTA | produce | 23.30 | 17.20 | 17.38 | 17.38 | **15.52** | ridge (+6.10) | **ou (+7.79)** |
| INDIAN_CHILIES | produce | 19.03 | 15.00 | 15.16 | 15.16 | **14.11** | ridge (+4.03) | **ou (+4.92)** |
| RED_ONION_INDIA | produce | 10.43 | 9.28 | 11.77 | 11.54 | 20.76 | ridge (+1.14) | ridge (+1.14) |
| PEANUTS | produce | 8.06 | 7.22 | 6.98 | 6.98 | 8.61 | gbm (+1.08) | gbm (+1.08) |
| CHINESE_GARLIC | produce | 13.40 | 15.04 | 14.29 | 14.12 | 19.16 | naive (0.00) | naive (0.00) |
| COCOA | futures | 10.01 | 9.69 | 9.40 | 10.31 | **8.18** | gbm (+0.61) | **ou (+1.84)** |
| WHEAT | futures | 5.69 | 5.95 | 7.85 | 6.80 | **5.12** | naive (0.00) | **ou (+0.58)** |
| RICE | futures | 4.83 | 5.25 | 5.48 | 5.66 | **4.46** | naive (0.00) | **ou (+0.37)** |
| SOYBEAN | futures | 5.00 | 4.10 | 4.73 | 7.37 | 5.67 | ridge (+0.90) | ridge (+0.90) |
| CORN | futures | 7.06 | 7.32 | 6.61 | 9.09 | 7.09 | gbm (+0.45) | gbm (+0.45) |
| CRUDE_OIL | futures | 9.73 | 9.39 | 10.51 | 11.30 | 10.17 | ridge (+0.33) | ridge (+0.33) |
| COPPER | futures | 3.83 | 3.68 | 4.18 | 5.57 | 4.56 | ridge (+0.16) | ridge (+0.16) |
| GOLD | futures | 5.03 | 5.56 | 6.25 | 5.95 | 5.51 | naive (0.00) | naive (0.00) |
| SUGAR | futures | 5.88 | 7.45 | 6.21 | 7.88 | 7.34 | naive (0.00) | naive (0.00) |
| FREIGHT_INDICES | futures | 8.16 | 8.15 | 10.19 | 8.98 | 8.80 | naive (0.00) | naive (0.00) |

## Verdict

- **OU improves the best-of in 5/15 commodities with ZERO regressions.** It is picked
  for **ROBUSTA, INDIAN_CHILIES, COCOA, WHEAT, RICE**; everywhere else the margin rule
  correctly leaves it out (e.g. OU is poor on RED_ONION/GARLIC and is not selected).
- The two cyclical-produce stars (robusta, chilli) gain the most — consistent with the
  prior finding that mean-reversion is their value driver. OU also rescues three futures
  where nothing previously beat naive or beat the incumbent (cocoa, wheat, rice).
- Because selection goes through the unchanged best-of + naive-margin rule, adding OU is
  **strictly safe** (it can only be chosen when it beats the alternatives by the margin).

## Decision & follow-up

OU is committed as a **research-only candidate**: `OUForecaster`, `walk_forward_ou`,
and the `ml/backtests/research_pool` comparison harness. It is **NOT** wired into the
production forecaster (`ml/forecast.py`) and changes no production default. Given the
clean, regression-free evidence, the recommended (separately-approved) follow-up is to
add `ou` to the production best-of pool behind the same margin rule — a small, guarded
change evaluated per-commodity by the existing walk-forward.
