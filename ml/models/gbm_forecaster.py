"""Gradient-boosted (XGBoost) autoregressive forecaster.

Same point-in-time features and anchored-ramp forecast as ``RidgeARForecaster``,
but the regressor is a gradient-boosted tree ensemble, which captures non-linear
feature interactions (e.g. mean-reversion that only kicks in in a high-volatility
regime). It earns its keep on the harder, spikier produce series (garlic, chilli)
where the linear model can't.

XGBoost is imported lazily and treated as OPTIONAL: if it isn't installed,
``is_available()`` returns False and the forecast layer simply skips this model
and selects between the Ridge AR model and naive instead. Determinism is pinned
with ``seed`` + single-threaded training.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ml.features.tabular import feature_row, training_matrix

# tree params (shallow + regularised for ~1-2k noisy samples); seed+1 thread ⇒ deterministic
DEFAULT_PARAMS: dict[str, Any] = {
    "max_depth": 3,
    "eta": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "lambda": 1.0,
    "objective": "reg:squarederror",
    "seed": 0,
    "nthread": 1,
    "verbosity": 0,
}
NUM_ROUND = 250
MIN_ROWS = 80  # need enough samples before trees beat a flat prediction


def is_available() -> bool:
    """True when xgboost can be imported (it is an optional dependency)."""
    try:
        import xgboost  # noqa: F401

        return True
    except Exception:
        return False


@dataclass
class GBMForecaster:
    horizon: int
    num_round: int = NUM_ROUND
    params: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    cycle_periods: Sequence[float] = ()  # multi-year cycle periods (rows); () = none
    booster_: Any = None  # None ⇒ predicts zero return ⇒ falls back to naive
    ret_sigma_: float = 0.0

    def fit(self, logy: np.ndarray, doy: np.ndarray, *, end: int | None = None) -> GBMForecaster:
        import xgboost as xgb

        x, y = training_matrix(logy, doy, horizon=self.horizon, end=end, cycle_periods=self.cycle_periods)
        if x.shape[0] >= MIN_ROWS:
            dtrain = xgb.DMatrix(x[:, 1:], label=y)  # drop the intercept column for trees
            self.booster_ = xgb.train(self.params, dtrain, num_boost_round=self.num_round)
        else:
            self.booster_ = None
        window = logy[:end] if end is not None else logy
        self.ret_sigma_ = float(np.std(np.diff(window), ddof=1)) if len(window) > 1 else 0.0
        return self

    def predict_return(self, logy: np.ndarray, doy: np.ndarray, i: int) -> float:
        if self.booster_ is None:
            return 0.0
        import xgboost as xgb

        feat = feature_row(logy, doy, i, cycle_periods=self.cycle_periods)[1:].reshape(1, -1)
        return float(self.booster_.predict(xgb.DMatrix(feat))[0])

    def forecast(self, logy: np.ndarray, doy: np.ndarray, anchor_idx: int, y_anchor: float, steps: int) -> np.ndarray:
        total = self.predict_return(logy, doy, anchor_idx)
        k = np.arange(1, steps + 1, dtype=float)
        return float(y_anchor) * np.exp(total * k / float(self.horizon))

    def forecast_interval(
        self, logy: np.ndarray, doy: np.ndarray, anchor_idx: int, y_anchor: float, steps: int, *, z: float = 1.2816
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        point = self.forecast(logy, doy, anchor_idx, y_anchor, steps)
        s = np.arange(1, steps + 1)
        band = z * self.ret_sigma_ * np.sqrt(s)
        return point, point * np.exp(-band), point * np.exp(band)
