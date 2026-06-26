"""Ridge autoregressive forecaster — the model that actually beats the naive
random-walk on most commodities.

It predicts the ``horizon``-day-ahead **log-return** from point-in-time features
(momentum + mean-reversion + seasonality, see ``ml.features.tabular``) via ridge
regression (closed form ⇒ fully deterministic, no RNG, no extra dependency). The
forecast is anchored to the last price and the predicted total return is laid
down as a constant-drift ramp over the horizon. The intercept is left
unpenalised so the model keeps an unbiased average drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ml.features.tabular import feature_row, training_matrix


@dataclass
class RidgeARForecaster:
    horizon: int
    l2: float = 5.0
    coef_: np.ndarray = field(default_factory=lambda: np.empty(0))
    ret_sigma_: float = 0.0  # daily log-return std (drives the widening band)

    def fit(
        self, logy: np.ndarray, doy: np.ndarray, *, exog_features: np.ndarray | None = None, end: int | None = None
    ) -> RidgeARForecaster:
        x, y = training_matrix(logy, doy, horizon=self.horizon, end=end, exog_features=exog_features)
        p = x.shape[1]
        if x.shape[0] < p + 1:  # not enough rows to fit reliably
            self.coef_ = np.zeros(p)  # ⇒ predicts zero return ⇒ falls back to naive
        else:
            a = x.T @ x + self.l2 * np.eye(p)
            a[0, 0] -= self.l2  # do not penalise the intercept
            self.coef_ = np.linalg.solve(a, x.T @ y)
        window = logy[:end] if end is not None else logy
        self.ret_sigma_ = float(np.std(np.diff(window), ddof=1)) if len(window) > 1 else 0.0
        return self

    def predict_return(
        self, logy: np.ndarray, doy: np.ndarray, i: int, *, exog_features: np.ndarray | None = None
    ) -> float:
        """Predicted total log-return over ``horizon`` days, from features at ``i``."""
        return float(feature_row(logy, doy, i, exog_features=exog_features) @ self.coef_)

    def forecast(
        self,
        logy: np.ndarray,
        doy: np.ndarray,
        anchor_idx: int,
        y_anchor: float,
        steps: int,
        *,
        exog_features: np.ndarray | None = None,
    ) -> np.ndarray:
        """Anchored trajectory: ramp the predicted total return over ``horizon`` days."""
        total = self.predict_return(logy, doy, anchor_idx, exog_features=exog_features)
        k = np.arange(1, steps + 1, dtype=float)
        cum = total * k / float(self.horizon)  # constant-drift ramp in cumulative log-return
        return float(y_anchor) * np.exp(cum)

    def forecast_interval(
        self,
        logy: np.ndarray,
        doy: np.ndarray,
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
