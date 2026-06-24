"""Walk-forward (rolling-origin) backtest — honest out-of-sample error.

Each fold trains ONLY on data up to the cutoff and forecasts the next ``horizon``
points, so it cannot see the future (no look-ahead). Reports the baseline's
MAPE/RMSE alongside the naive benchmark's MAPE so accuracy claims are grounded.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ml.models.baseline import FourierTrendForecaster, naive_last


@dataclass
class BacktestResult:
    horizon: int
    folds: int
    model_mape: float
    model_rmse: float
    naive_mape: float

    @property
    def beats_naive(self) -> bool:
        return self.folds > 0 and self.model_mape < self.naive_mape


def _mape(actual: np.ndarray, pred: np.ndarray) -> float:
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    mask = a != 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((a[mask] - p[mask]) / a[mask])) * 100.0)


def _rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(actual, dtype=float) - np.asarray(pred, dtype=float)) ** 2)))


def walk_forward(
    t: np.ndarray, y: np.ndarray, *, horizon: int, folds: int = 5, min_train: int = 252, harmonics: int = 3
) -> BacktestResult:
    ti = np.asarray(t)
    yv = np.asarray(y, dtype=float)
    n = len(yv)

    model_mapes: list[float] = []
    model_rmses: list[float] = []
    naive_mapes: list[float] = []

    last_cut = n - horizon
    if last_cut > min_train:
        cuts = np.unique(np.linspace(min_train, last_cut, folds).astype(int))
        for cut in cuts:
            if cut < min_train or cut + horizon > n:
                continue
            model = FourierTrendForecaster(harmonics=harmonics).fit(ti[:cut], yv[:cut])
            actual = yv[cut : cut + horizon]
            pred = model.forecast(ti[cut - 1], yv[cut - 1], ti[cut : cut + horizon])  # anchored, out-of-sample
            model_mapes.append(_mape(actual, pred))
            model_rmses.append(_rmse(actual, pred))
            naive_mapes.append(_mape(actual, naive_last(yv[:cut], horizon)))

    return BacktestResult(
        horizon=horizon,
        folds=len(model_mapes),
        model_mape=float(np.mean(model_mapes)) if model_mapes else float("nan"),
        model_rmse=float(np.mean(model_rmses)) if model_rmses else float("nan"),
        naive_mape=float(np.mean(naive_mapes)) if naive_mapes else float("nan"),
    )
