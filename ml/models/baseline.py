"""Transparent baseline forecasters.

``FourierTrendForecaster`` fits ``log(price) = trend + annual Fourier`` by OLS
(numpy lstsq). For forecasting it is **anchored to the last observed price** and
applies only the model's trend+seasonal *increment* — commodity prices are near
random walks, so projecting the absolute fitted level regresses toward the trend
line and loses to the naive benchmark. ``naive_last`` is that benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ml.features.seasonal import ANNUAL, design_matrix


@dataclass
class FourierTrendForecaster:
    harmonics: int = 3
    # Damped trend (Gardner): the linear-trend increment beyond the anchor decays
    # geometrically per day, so a steep fitted slope can't extrapolate without
    # bound (the #1 cause of the baseline overshooting on volatile produce). The
    # seasonal/harmonic part is left intact. 1.0 = undamped (original behaviour);
    # phi<1 caps the total trend move at slope_per_day * phi/(1-phi).
    trend_damping: float = 1.0
    coef_: np.ndarray = field(default_factory=lambda: np.empty(0))
    resid_sigma_: float = 0.0  # log-residual std (fit quality)
    ret_sigma_: float = 0.0  # daily log-return std (drives the widening band)

    def fit(self, t: np.ndarray, y: np.ndarray) -> FourierTrendForecaster:
        yv = np.asarray(y, dtype=float)
        logy = np.log(yv)
        x = design_matrix(t, harmonics=self.harmonics)
        beta, *_ = np.linalg.lstsq(x, logy, rcond=None)
        dof = max(1, x.shape[0] - x.shape[1])
        self.coef_ = beta
        self.resid_sigma_ = float(np.sqrt(np.sum((logy - x @ beta) ** 2) / dof))
        self.ret_sigma_ = float(np.std(np.diff(logy), ddof=1)) if len(logy) > 1 else 0.0
        return self

    def _mu(self, t: np.ndarray) -> np.ndarray:
        return design_matrix(t, harmonics=self.harmonics) @ self.coef_

    def _mu_seasonal(self, t: np.ndarray) -> np.ndarray:
        """Fitted level WITHOUT the linear-trend column (intercept + harmonics)."""
        coef = self.coef_.copy()
        coef[1] = 0.0  # zero the trend coefficient
        return design_matrix(t, harmonics=self.harmonics) @ coef

    def predict(self, t: np.ndarray) -> np.ndarray:
        """Absolute fitted level (for inspecting fit quality, not forecasting)."""
        return np.exp(self._mu(t))

    def forecast(self, t_anchor: float, y_anchor: float, t_future: np.ndarray) -> np.ndarray:
        """Anchored forecast: start at the last actual price and apply the model's
        seasonal increment (full) plus a damped linear-trend increment."""
        tf = np.asarray(t_future, dtype=float)
        ta = float(t_anchor)
        seasonal_inc = self._mu_seasonal(tf) - float(self._mu_seasonal(np.array([ta]))[0])
        slope_per_day = float(self.coef_[1]) / ANNUAL  # d/dt of the (coef[1] * t/period) trend term
        d = tf - ta
        phi = self.trend_damping
        # damped cumulative trend distance: sum_{k=1..d} phi^k -> d when phi>=1, else saturates
        damped_d = d if phi >= 1.0 else phi * (1.0 - np.power(phi, d)) / (1.0 - phi)
        increment = seasonal_inc + slope_per_day * damped_d
        return float(y_anchor) * np.exp(increment)

    def forecast_interval(
        self, t_anchor: float, y_anchor: float, t_future: np.ndarray, *, z: float = 1.2816
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Anchored point + a random-walk band that widens with horizon (~80% at z=1.2816)."""
        point = self.forecast(t_anchor, y_anchor, t_future)
        steps = np.arange(1, len(np.asarray(t_future)) + 1)
        band = z * self.ret_sigma_ * np.sqrt(steps)
        return point, point * np.exp(-band), point * np.exp(band)


def naive_last(y: np.ndarray, steps: int) -> np.ndarray:
    """Random-walk benchmark: repeat the last observed value."""
    return np.repeat(float(np.asarray(y, dtype=float)[-1]), steps)
