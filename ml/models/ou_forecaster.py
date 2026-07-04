"""Ornstein-Uhlenbeck / damped mean-reversion forecaster (Phase 8A, research).

Models the **restoring force** the deep-research report attributes to the RLC
engine, but as a transparent, deterministic, point-in-time univariate model — no
new data, no metaphor-gate. The idea:

  * a *slow trend* ``m_t`` = causal trailing mean of log-price,
  * a *deviation* ``d_t = log(price_t) - m_t`` (how far price sits from trend),
  * the deviation reverts geometrically: ``d_{t+k} = phi^k * d_t`` with
    ``phi in [0,1)`` the per-step persistence (``kappa = 1 - phi`` is the
    mean-reversion speed of the discrete OU / AR(1) process), and
  * the slow trend continues with a **damped** (bounded) drift so a steep recent
    slope cannot extrapolate without bound.

The forecast is anchored to the last observed price, exactly like the Ridge and
Fourier baselines, so it composes with the existing walk-forward harness and the
naive benchmark unchanged.

Closed form ⇒ fully deterministic (no RNG, no extra dependency, no DB/network).
Fails closed (flat = naive) on insufficient history or non-finite log-price
(e.g. a non-positive price upstream produces a non-finite log and is rejected).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def causal_trailing_mean(x: np.ndarray, window: int) -> np.ndarray:
    """Causal trailing simple moving average (point-in-time slow trend).

    ``out[t]`` uses only ``x[max(0, t-window+1) .. t]`` — never any future value —
    so it is safe to compute over a whole series and slice. Vectorised via a prefix
    sum; the leading ``window-1`` points use the available (expanding) prefix.
    """
    xv = np.asarray(x, dtype=float)
    n = xv.shape[0]
    if n == 0:
        return np.empty(0, dtype=float)
    w = max(1, int(window))
    csum = np.cumsum(xv)
    out = np.empty(n, dtype=float)
    k = np.arange(n)
    small = k < w  # expanding window before the first full window
    out[small] = csum[k[small]] / (k[small] + 1.0)
    big = ~small
    kb = k[big]
    out[big] = (csum[kb] - csum[kb - w]) / float(w)
    return out


@dataclass
class OUForecaster:
    """Anchored damped mean-reversion forecaster.

    Parameters
    ----------
    horizon : int
        Forecast horizon in trading days (matches the other forecasters).
    trend_span : int
        Window of the causal trailing mean used as the slow trend.
    trend_damping : float
        Geometric damping (Gardner) on the slow-trend drift; ``< 1`` bounds the
        cumulative trend move, ``>= 1`` lets it continue linearly.
    drift_lookback : int
        Window over which the slow-trend per-step drift is measured.
    """

    horizon: int
    trend_span: int = 90
    trend_damping: float = 0.97
    drift_lookback: int = 60
    phi_: float = 0.0  # mean-reversion persistence per step in [0, 1); kappa = 1 - phi
    g_: float = 0.0  # per-step slow-trend drift (log units)
    ret_sigma_: float = 0.0  # daily log-return std (drives the widening band)
    degenerate_: bool = True  # True until a valid fit ⇒ forecast falls back to naive

    def _min_history(self) -> int:
        return max(self.trend_span + self.horizon + 5, self.drift_lookback + 5, 30)

    def fit(
        self,
        logy: np.ndarray,
        doy: np.ndarray | None = None,
        *,
        exog_features: np.ndarray | None = None,  # accepted for interface parity; OU is univariate
        end: int | None = None,
    ) -> OUForecaster:
        window = np.asarray(logy, dtype=float)
        window = window[:end] if end is not None else window
        n = window.shape[0]

        # Fail closed: too short, or non-finite (a non-positive price upstream
        # makes log non-finite) ⇒ behave as naive.
        if n < self._min_history() or not np.isfinite(window).all():
            self.phi_, self.g_, self.degenerate_ = 0.0, 0.0, True
            self.ret_sigma_ = float(np.std(np.diff(window), ddof=1)) if n > 1 and np.isfinite(window).all() else 0.0
            return self

        m = causal_trailing_mean(window, self.trend_span)
        d = window - m  # deviation from the slow trend

        # Mean-reversion persistence: OLS-through-origin of d_{t+1} on d_t, so the
        # deviation reverts toward the trend (0), not toward a biased level.
        d0, d1 = d[:-1], d[1:]
        denom = float(d0 @ d0)
        phi = float(d0 @ d1) / denom if denom > 0.0 else 0.0
        self.phi_ = float(min(max(phi, 0.0), 0.999))

        # Damped slow-trend drift, measured over the recent lookback only.
        lookback = min(self.drift_lookback, n - 1)
        self.g_ = float((m[-1] - m[-1 - lookback]) / lookback) if lookback > 0 else 0.0

        self.ret_sigma_ = float(np.std(np.diff(window), ddof=1)) if n > 1 else 0.0
        self.degenerate_ = False
        return self

    def _trend_steps(self, steps: int) -> np.ndarray:
        """Damped cumulative trend factor S_k = sum_{j=1..k} damping^{j-1}."""
        k = np.arange(1, steps + 1, dtype=float)
        phi = self.trend_damping
        if phi >= 1.0:
            return k
        return (1.0 - np.power(phi, k)) / (1.0 - phi)

    def forecast(
        self,
        logy: np.ndarray,
        doy: np.ndarray | None,
        anchor_idx: int,
        y_anchor: float,
        steps: int,
        *,
        exog_features: np.ndarray | None = None,
    ) -> np.ndarray:
        """Anchored trajectory: damped slow-trend drift + geometric reversion of the
        current deviation toward the trend. Flat (naive) when not validly fit."""
        if self.degenerate_ or steps <= 0:
            return np.repeat(float(y_anchor), max(0, steps))

        window = np.asarray(logy, dtype=float)[: anchor_idx + 1]
        if window.shape[0] < 2 or not np.isfinite(window).all():
            return np.repeat(float(y_anchor), steps)

        m = causal_trailing_mean(window, self.trend_span)
        d_anchor = float(window[-1] - m[-1])

        k = np.arange(1, steps + 1, dtype=float)
        trend_term = self.g_ * self._trend_steps(steps)
        reversion_term = (np.power(self.phi_, k) - 1.0) * d_anchor  # pulls price back toward trend
        # Anchored to y_anchor: delta is the increment relative to the last price.
        delta = trend_term + reversion_term
        return float(y_anchor) * np.exp(delta)

    def forecast_interval(
        self,
        logy: np.ndarray,
        doy: np.ndarray | None,
        anchor_idx: int,
        y_anchor: float,
        steps: int,
        *,
        exog_features: np.ndarray | None = None,
        z: float = 1.2816,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Point trajectory + a random-walk band widening with horizon (~80% at z=1.2816)."""
        point = self.forecast(logy, doy, anchor_idx, y_anchor, steps, exog_features=exog_features)
        s = np.arange(1, steps + 1)
        band = z * self.ret_sigma_ * np.sqrt(s)
        return point, point * np.exp(-band), point * np.exp(band)
