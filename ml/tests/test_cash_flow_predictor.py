"""Tests for the cash-flow + Fourier CashFlowFourierPredictor."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.models.cash_flow_predictor import (
    CashFlowFourierPredictor,
    SupplyConfig,
    _shift_by_months,
)


def _synthetic_history(
    n: int = 60,
    *,
    harvest_lag: float = 6.0,
    seed: int = 0,
) -> tuple[pd.DataFrame, SupplyConfig]:
    """Build a series where price ≈ M / Q + seasonal residual (recoverable by fit)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="MS")
    t = np.arange(n, dtype=float)
    planted = 80.0 + 20.0 * np.sin(2 * np.pi * t / 12.0) + rng.normal(0, 1.0, n)
    imports = 30.0 + 5.0 * np.cos(2 * np.pi * t / 6.0)
    inventory = 40.0 + rng.normal(0, 2.0, n)
    weather = np.full(n, 1.0)
    cfg = SupplyConfig(
        harvest_lag_months=harvest_lag,
        import_lag_months=1.0,
        yield_tonnes_per_ha=2.0,
        loss_fraction=0.10,
        m_flow_window_months=6,
        fourier_periods_months=(12.0, 6.0),
        trend_degree=1,
    )
    domestic = _shift_by_months(planted, harvest_lag) * cfg.yield_tonnes_per_ha
    lagged_imp = _shift_by_months(imports, cfg.import_lag_months)
    gross = inventory + domestic + lagged_imp
    q = np.maximum(gross * (1.0 - cfg.loss_fraction), cfg.q_floor)
    m_flow = 50_000.0
    seasonal = 200.0 * np.sin(2 * np.pi * t / 12.0) + 80.0 * np.cos(2 * np.pi * t / 6.0)
    trend = 10.0 * t
    price = m_flow / q + trend + seasonal + rng.normal(0, 5.0, n)
    df = pd.DataFrame(
        {
            "date": dates,
            "price": price,
            "planted_area": planted,
            "import_volume": imports,
            "inventory": inventory,
            "weather_index": weather,
        }
    )
    return df, cfg


def test_shift_by_months_lags_and_zero_fills() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert np.allclose(_shift_by_months(x, 2), [0.0, 0.0, 1.0, 2.0])


def test_fit_predict_deterministic_and_shaped() -> None:
    df, cfg = _synthetic_history(n=48, seed=3)
    a = CashFlowFourierPredictor(cfg).fit(df)
    b = CashFlowFourierPredictor(cfg).fit(df)
    future = pd.date_range("2024-01-01", periods=6, freq="MS")
    fa = a.predict(future)
    fb = b.predict(future)
    assert np.allclose(fa["price_pred"], fb["price_pred"])
    assert list(fa.columns) == [
        "date",
        "price_pred",
        "q",
        "m_flow",
        "p_mechanical",
        "p_trend_fourier",
    ]
    assert len(fa) == 6
    assert np.all(np.isfinite(fa["price_pred"]))
    assert np.all(fa["q"] > 0)


def test_in_sample_fit_tracks_synthetic_price() -> None:
    df, cfg = _synthetic_history(n=60, seed=1)
    model = CashFlowFourierPredictor(cfg).fit(df)
    components = model.fitted_components()
    corr = np.corrcoef(components["price"], components["price_fitted"])[0, 1]
    assert corr > 0.95


def test_higher_supply_lowers_mechanical_price() -> None:
    df, cfg = _synthetic_history(n=36, seed=2)
    model = CashFlowFourierPredictor(cfg).fit(df)
    future = pd.date_range(df["date"].iloc[-1] + pd.offsets.MonthBegin(1), periods=3, freq="MS")
    base_drivers = pd.DataFrame(
        {
            "date": future,
            "planted_area": 100.0,
            "import_volume": 40.0,
            "inventory": 50.0,
        }
    )
    tight = base_drivers.copy()
    tight["inventory"] = 20.0
    ample = base_drivers.copy()
    ample["inventory"] = 200.0
    p_tight = model.predict(future, future_drivers=tight)["p_mechanical"].to_numpy()
    p_ample = model.predict(future, future_drivers=ample)["p_mechanical"].to_numpy()
    assert np.all(p_tight > p_ample)


def test_backtest_chronological_returns_finite_metrics() -> None:
    df, cfg = _synthetic_history(n=48, seed=4)
    model = CashFlowFourierPredictor(cfg).fit(df)
    result = model.backtest(test_size=0.25)
    assert result.n_test == 12
    assert np.isfinite(result.mae)
    assert np.isfinite(result.rmse)
    assert np.isfinite(result.mape)
    assert result.mae >= 0
    assert result.rmse >= result.mae * 0.5  # loose sanity


def test_rejects_commodity_named_lag_keys() -> None:
    df, cfg = _synthetic_history(n=36, seed=5)
    model = CashFlowFourierPredictor(cfg)
    with pytest.raises(ValueError, match="commodity-named"):
        model.fit(df, lags={"garlic": 6})


def test_lag_override_harvest_months() -> None:
    df, _ = _synthetic_history(n=36, harvest_lag=6.0, seed=6)
    model = CashFlowFourierPredictor(SupplyConfig(harvest_lag_months=3.0))
    model.fit(df, lags={"harvest_months": 6.0})
    assert model.config.harvest_lag_months == 6.0


def test_missing_columns_raise() -> None:
    df, cfg = _synthetic_history(n=24, seed=7)
    model = CashFlowFourierPredictor(cfg)
    with pytest.raises(ValueError, match="missing required"):
        model.fit(df.drop(columns=["inventory"]))


def test_predict_before_fit_raises() -> None:
    model = CashFlowFourierPredictor()
    with pytest.raises(RuntimeError, match="fit"):
        model.predict(pd.date_range("2026-01-01", periods=3, freq="MS"))
