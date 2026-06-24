"""Forecasting baseline: design matrix, model fit, honest backtest (no DB/network)."""

from __future__ import annotations

import numpy as np

from ml.backtests.walk_forward import walk_forward
from ml.features.seasonal import design_matrix
from ml.models.baseline import FourierTrendForecaster, naive_last


def _trend_seasonal(n: int = 700) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(n, dtype=float)
    logy = 4.0 + 0.0005 * t + 0.1 * np.sin(2.0 * np.pi * t / 365.25)
    return t, np.exp(logy)


def test_design_matrix_shape() -> None:
    x = design_matrix(np.arange(10), harmonics=3)
    assert x.shape == (10, 2 + 2 * 3)  # intercept + trend + sin/cos per harmonic


def test_model_recovers_trend_and_seasonality() -> None:
    t, y = _trend_seasonal()
    model = FourierTrendForecaster(harmonics=3).fit(t, y)
    mape = float(np.mean(np.abs((y - model.predict(t)) / y)) * 100)
    assert mape < 1.0  # near-perfect fit on a clean generated signal


def test_forecast_interval_brackets_point() -> None:
    t, y = _trend_seasonal()
    model = FourierTrendForecaster().fit(t, y)
    t_future = t[-1] + np.arange(1, 6)
    point, lower, upper = model.forecast_interval(float(t[-1]), float(y[-1]), t_future)
    assert np.all(lower <= point) and np.all(point <= upper)
    assert (upper - lower)[-1] >= (upper - lower)[0]  # band widens with horizon


def test_walk_forward_is_honest_and_beats_naive_on_seasonal() -> None:
    t, y = _trend_seasonal(800)
    result = walk_forward(t, y, horizon=30, folds=4, min_train=365)
    assert result.folds > 0
    assert np.isfinite(result.model_mape) and np.isfinite(result.naive_mape)
    assert result.beats_naive  # a clean trend+seasonal series should beat last-value


def test_naive_last_repeats_last_value() -> None:
    assert list(naive_last(np.array([1.0, 2.0, 3.0]), 3)) == [3.0, 3.0, 3.0]
