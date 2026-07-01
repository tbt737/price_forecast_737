"""Van der Pol nonlinear damped-oscillator forecaster (Phase ECON-1A, RESEARCH ONLY).

The econophysics report models a price bubble as a **forced Van der Pol oscillator**:
the deviation of price from its slow trend behaves like a self-sustaining oscillator
whose damping flips sign — it pumps energy while the deviation is small (bubble build-up)
and brakes hard once the deviation is large (the boom-bust limit cycle / Hopf bifurcation).

This is the **nonlinear generalization of the existing OU candidate** (which is a *linear*
damped mean-reversion). It is deliberately kept transparent and deterministic so it plugs
into the same walk-forward harness and the naive benchmark unchanged:

  * slow trend ``m_t`` = causal trailing mean of log-price (same as OU),
  * deviation ``d_t = log(price_t) - m_t``, **normalized** ``z_t = d_t / sigma_d`` so the
    ``(1 - z^2)`` nonlinearity only activates when the deviation exceeds ~1 std (the bubble
    threshold) — in log-space raw deviations are tiny and would leave VdP ≈ linear,
  * fit ``z'' = mu (1 - z^2) z' - w2 z`` by OLS on the causal discrete (velocity, accel)
    of ``z`` — closed-form, deterministic, no RNG,
  * forecast by integrating that ODE forward from the anchor state with
    ``scipy.integrate.solve_ivp`` (fixed method/tolerances ⇒ deterministic), plus the same
    damped slow-trend drift as OU, anchored to the last price.

RESEARCH ONLY: not imported by ``ml/forecast.py`` or the production runner. No DB, no
network, no import-time side effects. **Fails closed to flat (= naive)** on short history,
non-finite log-price, a non-restoring / unstable fit, or any numerical blow-up in the
integration — it must never crash a backtest fold.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ml.models.ou_forecaster import causal_trailing_mean

_Z_CAP = 8.0  # |z| beyond this in the integrated trajectory ⇒ treat as blown up
_DELTA_CAP = 0.5  # clip |log-move| to ±0.5 (~±65%) so a runaway oscillation can't fabricate absurd prices


@dataclass
class VdPForecaster:
    """Anchored nonlinear (Van der Pol) oscillator forecaster. Research candidate."""

    horizon: int
    trend_span: int = 90
    trend_damping: float = 0.97
    drift_lookback: int = 60
    mu_max: float = 5.0
    w2_max: float = 4.0
    # fitted state
    mu_: float = 0.0
    w2_: float = 0.0
    sigma_d_: float = 0.0
    g_: float = 0.0
    ret_sigma_: float = 0.0
    degenerate_: bool = True

    def _min_history(self) -> int:
        return max(self.trend_span + self.horizon + 5, self.drift_lookback + 5, 60)

    def fit(
        self,
        logy: np.ndarray,
        doy: np.ndarray | None = None,
        *,
        exog_features: np.ndarray | None = None,  # accepted for interface parity; VdP core is univariate
        end: int | None = None,
    ) -> VdPForecaster:
        window = np.asarray(logy, dtype=float)
        window = window[:end] if end is not None else window
        n = window.shape[0]

        finite = np.isfinite(window).all()
        self.ret_sigma_ = float(np.std(np.diff(window), ddof=1)) if n > 1 and finite else 0.0
        if n < self._min_history() or not finite:
            self.degenerate_ = True
            return self

        m = causal_trailing_mean(window, self.trend_span)
        d = window - m
        sigma_d = float(np.std(d, ddof=1))
        if not np.isfinite(sigma_d) or sigma_d <= 1e-9:
            self.degenerate_ = True
            return self
        z = d / sigma_d

        # Causal discrete dynamics of z: backward velocity, central acceleration.
        z_t = z[1:-1]                       # t = 1 .. n-2
        v_t = z[1:-1] - z[0:-2]             # z_t - z_{t-1}
        a_t = z[2:] - 2.0 * z[1:-1] + z[0:-2]  # z_{t+1} - 2 z_t + z_{t-1}

        # OLS: a = mu*(1 - z^2)*v - w2*z  ⇒ regress a on [(1-z^2)v, -z].
        feat = np.column_stack([(1.0 - z_t**2) * v_t, -z_t])
        if not np.isfinite(feat).all() or not np.isfinite(a_t).all():
            self.degenerate_ = True
            return self
        coef, *_ = np.linalg.lstsq(feat, a_t, rcond=None)
        mu, w2 = float(coef[0]), float(coef[1])

        # Guards: require a restoring, stable oscillator; clamp damping magnitude.
        if not (np.isfinite(mu) and np.isfinite(w2)) or w2 <= 1e-6 or w2 > self.w2_max:
            self.degenerate_ = True
            return self
        self.mu_ = float(min(max(mu, -self.mu_max), self.mu_max))
        self.w2_ = w2
        self.sigma_d_ = sigma_d

        lookback = min(self.drift_lookback, n - 1)
        self.g_ = float((m[-1] - m[-1 - lookback]) / lookback) if lookback > 0 else 0.0
        self.degenerate_ = False
        return self

    def _trend_steps(self, steps: int) -> np.ndarray:
        k = np.arange(1, steps + 1, dtype=float)
        phi = self.trend_damping
        return k if phi >= 1.0 else (1.0 - np.power(phi, k)) / (1.0 - phi)

    def _integrate_z(self, z0: float, v0: float, steps: int) -> np.ndarray | None:
        """Deterministic forward integration of the fitted VdP ODE. None on blow-up."""
        from scipy.integrate import solve_ivp

        mu, w2 = self.mu_, self.w2_

        def rhs(_t: float, y: np.ndarray) -> list[float]:
            zz, vv = y
            return [vv, mu * (1.0 - zz * zz) * vv - w2 * zz]

        try:
            sol = solve_ivp(
                rhs, (0.0, float(steps)), [float(z0), float(v0)],
                t_eval=np.arange(1, steps + 1, dtype=float),
                method="RK45", rtol=1e-6, atol=1e-8, max_step=1.0,
            )
        except (ValueError, RuntimeError, FloatingPointError):
            return None
        if not sol.success or sol.y.shape[1] != steps:
            return None
        zf = sol.y[0]
        if not np.isfinite(zf).all() or np.max(np.abs(zf)) > _Z_CAP:
            return None
        return zf

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
        """Anchored trajectory: damped slow-trend drift + nonlinear-oscillator evolution of
        the current deviation. Flat (= naive) whenever not validly fit or on any blow-up."""
        if self.degenerate_ or steps <= 0 or self.sigma_d_ <= 0:
            return np.repeat(float(y_anchor), max(0, steps))

        window = np.asarray(logy, dtype=float)[: anchor_idx + 1]
        if window.shape[0] < 3 or not np.isfinite(window).all():
            return np.repeat(float(y_anchor), steps)

        m = causal_trailing_mean(window, self.trend_span)
        d = window - m
        d_anchor = float(d[-1])
        z0 = d_anchor / self.sigma_d_
        v0 = float(d[-1] - d[-2]) / self.sigma_d_

        zf = self._integrate_z(z0, v0, steps)
        if zf is None:  # fail closed to naive rather than crash / fabricate
            return np.repeat(float(y_anchor), steps)

        deviation_term = zf * self.sigma_d_ - d_anchor  # change in deviation from anchor
        trend_term = self.g_ * self._trend_steps(steps)
        delta = np.clip(trend_term + deviation_term, -_DELTA_CAP, _DELTA_CAP)
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
