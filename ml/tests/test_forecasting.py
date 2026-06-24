"""Unit tests for the forecasting stack: point-in-time features, the Ridge AR
forecaster, the damped-trend baseline, and the walk-forward backtest.

The point-in-time tests are the important guard (CLAUDE.md §3 / ARCHITECTURE
§3.2): a feature row at index ``i`` must be invariant to anything that happens
after ``i``, otherwise the backtest would be optimistic by look-ahead.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from ml.backtests.walk_forward import walk_forward_ar
from ml.features.tabular import LOOKBACK, feature_row, training_matrix
from ml.models.baseline import FourierTrendForecaster
from ml.models.gbm_forecaster import GBMForecaster, is_available
from ml.models.ridge_forecaster import RidgeARForecaster


def _doy(n: int) -> np.ndarray:
    return np.array([(i % 365) + 1 for i in range(n)], dtype=float)


# ── point-in-time correctness ────────────────────────────────────────────────
def test_feature_row_ignores_the_future() -> None:
    logy = np.log(np.linspace(100.0, 130.0, 120))
    doy = _doy(120)
    before = feature_row(logy.copy(), doy, 80)
    corrupted = logy.copy()
    corrupted[81:] = -999.0  # mangle everything after index 80
    after = feature_row(corrupted, doy, 80)
    assert np.allclose(before, after)


def test_training_matrix_does_not_peek_past_end() -> None:
    n = 400
    logy = np.log(np.linspace(100.0, 200.0, n))
    doy = _doy(n)
    end, horizon = 200, 30
    x, y = training_matrix(logy, doy, horizon=horizon, end=end)
    # last usable feature index is end-horizon-1; rows = (end-horizon) - LOOKBACK
    assert x.shape[0] == (end - horizon) - LOOKBACK
    # invariance: corrupting data at/after `end` must not change the matrix
    corrupt = logy.copy()
    corrupt[end:] = 0.0
    x2, y2 = training_matrix(corrupt, doy, horizon=horizon, end=end)
    assert np.allclose(x, x2) and np.allclose(y, y2)


# ── Ridge AR forecaster ───────────────────────────────────────────────────────
def test_ridge_is_deterministic() -> None:
    rng = np.random.default_rng(7)
    logy = np.cumsum(rng.normal(0, 0.01, 400)) + np.log(100.0)
    doy = _doy(400)
    a = RidgeARForecaster(horizon=30).fit(logy, doy).coef_
    b = RidgeARForecaster(horizon=30).fit(logy, doy).coef_
    assert np.allclose(a, b)


def test_ridge_falls_back_to_flat_without_enough_history() -> None:
    logy = np.log(np.linspace(100.0, 110.0, 65))  # 65 < LOOKBACK + horizon
    doy = _doy(65)
    model = RidgeARForecaster(horizon=30).fit(logy, doy)
    assert np.allclose(model.coef_, 0.0)  # no rows -> zero coefficients
    traj = model.forecast(logy, doy, 64, 110.0, 5)
    assert np.allclose(traj, 110.0)  # zero predicted return -> flat = naive


def test_ridge_forecast_anchored_and_shaped() -> None:
    rng = np.random.default_rng(1)
    logy = np.cumsum(rng.normal(0, 0.01, 400)) + np.log(50.0)
    doy = _doy(400)
    model = RidgeARForecaster(horizon=30).fit(logy, doy)
    traj = model.forecast(logy, doy, 399, 50.0, 30)
    assert len(traj) == 30
    total = model.predict_return(logy, doy, 399)
    assert np.isclose(traj[-1], 50.0 * np.exp(total))  # endpoint hits the predicted return
    assert np.isclose(traj[0], 50.0 * np.exp(total / 30.0))  # ramped first step


# ── damped trend baseline ─────────────────────────────────────────────────────
def test_damped_trend_reduces_extrapolation() -> None:
    t = np.arange(300, dtype=float)
    y = np.exp(0.002 * t + np.log(100.0))  # steep upward log-trend
    undamped = FourierTrendForecaster(harmonics=1, trend_damping=1.0).fit(t, y)
    damped = FourierTrendForecaster(harmonics=1, trend_damping=0.9).fit(t, y)
    t_future = np.arange(300, 390, dtype=float)
    fu = undamped.forecast(299.0, float(y[-1]), t_future)
    fd = damped.forecast(299.0, float(y[-1]), t_future)
    assert fd[-1] < fu[-1]  # damping pulls the upward extrapolation back


# ── walk-forward backtest ─────────────────────────────────────────────────────
@pytest.mark.skipif(not is_available(), reason="xgboost not installed")
def test_gbm_is_deterministic_and_falls_back() -> None:
    rng = np.random.default_rng(5)
    logy = np.cumsum(rng.normal(0, 0.01, 400)) + np.log(100.0)
    doy = _doy(400)
    a = GBMForecaster(horizon=30).fit(logy, doy).predict_return(logy, doy, 399)
    b = GBMForecaster(horizon=30).fit(logy, doy).predict_return(logy, doy, 399)
    assert a == b  # seed + single thread ⇒ bit-for-bit deterministic
    # too few rows to fit ⇒ no booster ⇒ flat (naive) forecast
    short = np.log(np.linspace(100.0, 110.0, 90))
    sdoy = _doy(90)
    model = GBMForecaster(horizon=30).fit(short, sdoy)
    assert model.booster_ is None
    assert np.allclose(model.forecast(short, sdoy, 89, 110.0, 5), 110.0)


def test_walk_forward_ar_produces_finite_folds() -> None:
    n = 500
    rng = np.random.default_rng(3)
    values = np.exp(np.cumsum(rng.normal(0, 0.01, n)) + np.log(100.0))
    start = date(2020, 1, 1)
    dates = [start + timedelta(days=i) for i in range(n)]
    bt = walk_forward_ar(dates, values, horizon=20, min_train=200)
    assert bt.folds > 0
    assert np.isfinite(bt.model_mape) and np.isfinite(bt.naive_mape)
