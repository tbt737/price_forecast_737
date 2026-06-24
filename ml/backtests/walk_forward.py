"""Walk-forward (rolling-origin) backtest — honest out-of-sample error.

Each fold trains ONLY on data up to the cutoff and forecasts the next ``horizon``
points, so it cannot see the future (no look-ahead). Reports the baseline's
MAPE/RMSE alongside the naive benchmark's MAPE so accuracy claims are grounded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import numpy as np

from ml.features.cycles import detect_cycles
from ml.models.baseline import FourierTrendForecaster, naive_last
from ml.models.gbm_forecaster import GBMForecaster
from ml.models.ridge_forecaster import RidgeARForecaster


def _rows_per_year(dates: list[date], n: int) -> float:
    span_days = max(1, (dates[-1] - dates[0]).days)
    return n / (span_days / 365.25)


class _AnchoredModel(Protocol):
    def fit(self, logy: np.ndarray, doy: np.ndarray, *, end: int | None = ...) -> Any: ...
    def forecast(
        self, logy: np.ndarray, doy: np.ndarray, anchor_idx: int, y_anchor: float, steps: int
    ) -> np.ndarray: ...


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
    t: np.ndarray,
    y: np.ndarray,
    *,
    horizon: int,
    folds: int = 5,
    min_train: int = 252,
    harmonics: int = 3,
    trend_damping: float = 1.0,
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
            model = FourierTrendForecaster(harmonics=harmonics, trend_damping=trend_damping).fit(ti[:cut], yv[:cut])
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


def _walk_forward_anchored(
    dates: list[date],
    values: np.ndarray,
    *,
    horizon: int,
    make_model: Callable[[int], _AnchoredModel],
    folds: int = 5,
    min_train: int = 252,
) -> BacktestResult:
    """Rolling-origin backtest for any anchored feature model. ``make_model(cut)``
    must return a model already fit ONLY on data before ``cut`` (``end=cut``) — the
    features are point-in-time, so this is an honest out-of-sample estimate."""
    yv = np.asarray(values, dtype=float)
    n = len(yv)
    logy = np.log(yv)
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)

    model_mapes: list[float] = []
    model_rmses: list[float] = []
    naive_mapes: list[float] = []

    last_cut = n - horizon
    if last_cut > min_train:
        for cut in np.unique(np.linspace(min_train, last_cut, folds).astype(int)):
            if cut < min_train or cut + horizon > n:
                continue
            model = make_model(int(cut))
            actual = yv[cut : cut + horizon]
            pred = model.forecast(logy, doy, int(cut) - 1, float(yv[cut - 1]), horizon)
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


def walk_forward_ar(
    dates: list[date], values: np.ndarray, *, horizon: int, folds: int = 5, min_train: int = 252, l2: float = 5.0
) -> BacktestResult:
    """Walk-forward backtest for the Ridge AR forecaster."""
    logy = np.log(np.asarray(values, dtype=float))
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
    return _walk_forward_anchored(
        dates,
        values,
        horizon=horizon,
        folds=folds,
        min_train=min_train,
        make_model=lambda cut: RidgeARForecaster(horizon=horizon, l2=l2).fit(logy, doy, end=cut),
    )


def walk_forward_gbm(
    dates: list[date],
    values: np.ndarray,
    *,
    horizon: int,
    folds: int = 5,
    min_train: int = 252,
    use_cycles: bool = False,
) -> BacktestResult:
    """Walk-forward backtest for the gradient-boosted (XGBoost) forecaster.

    With ``use_cycles``, each fold detects its multi-year cycle(s) from the training
    slice only (``logy[:cut]``) — point-in-time, so cycle periods can shift fold to
    fold ("no spring is identical") without leaking the future."""
    logy = np.log(np.asarray(values, dtype=float))
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
    rpy = _rows_per_year(dates, len(values))

    def make(cut: int) -> GBMForecaster:
        periods = detect_cycles(logy[:cut], rows_per_year=rpy) if use_cycles else []
        return GBMForecaster(horizon=horizon, cycle_periods=periods).fit(logy, doy, end=cut)

    return _walk_forward_anchored(
        dates, values, horizon=horizon, folds=folds, min_train=min_train, make_model=make
    )
