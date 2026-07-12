"""Tests for mechanistic_fourier_supply pool candidate."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ml.backtests.walk_forward import walk_forward_mechanistic
from ml.models.cash_flow_predictor import SupplyConfig
from ml.models.mechanistic_fourier import (
    MechanisticFourierForecaster,
    build_supply_frame,
    has_supply_drivers,
    resolve_supply_column,
)
from ml.predictor import CommodityPricePredictor


def _dates(n: int, start: date = date(2020, 1, 2)) -> list[date]:
    out: list[date] = []
    cursor = start
    while len(out) < n:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _panel(n: int = 400, *, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Price + supply exog where price ≈ M / Q + seasonal (recoverable)."""
    rng = np.random.default_rng(seed)
    dates = _dates(n)
    t = np.arange(n, dtype=float)
    planted = 80.0 + 15.0 * np.sin(2 * np.pi * t / 252.0)
    imports = 25.0 + 5.0 * np.cos(2 * np.pi * t / 126.0)
    inventory = 40.0 + rng.normal(0, 1.0, n)
    # Rough daily Q proxy (not exact monthly lag) so mechanistic has signal.
    q = np.maximum(inventory + 0.3 * planted + imports, 1.0)
    m_flow = 8_000.0
    seasonal = 30.0 * np.sin(2 * np.pi * t / 252.0)
    price = m_flow / q + seasonal + 100.0 + np.cumsum(rng.normal(0, 0.05, n))
    price = np.maximum(price, 1.0)
    price_df = pd.DataFrame({"date": dates, "value": price})
    exog = pd.DataFrame(
        {
            "date": dates,
            "planted_area": planted,
            "import_volume": imports,
            "inventory": inventory,
            "weather_index": np.ones(n),
        }
    )
    return price_df, exog


def test_resolve_supply_aliases() -> None:
    cols = ["Planted_Area", "imports", "cold_storage_inventory"]
    assert resolve_supply_column(cols, "planted_area") == "Planted_Area"
    assert resolve_supply_column(cols, "import_volume") == "imports"
    assert resolve_supply_column(cols, "inventory") == "cold_storage_inventory"
    assert has_supply_drivers(cols)


def test_has_supply_drivers_false_without_inventory() -> None:
    assert not has_supply_drivers(["planted_area", "import_volume"])


def test_build_supply_frame_none_without_drivers() -> None:
    dates = _dates(10)
    y = np.linspace(10, 12, 10)
    exog = np.ones((10, 1))
    assert build_supply_frame(dates, y, exog, ["foo"]) is None


def test_mechanistic_forecaster_deterministic() -> None:
    price_df, exog = _panel(n=360, seed=2)
    dates = [d.date() if hasattr(d, "date") else d for d in pd.to_datetime(price_df["date"])]
    y = price_df["value"].to_numpy(dtype=float)
    supply = build_supply_frame(
        dates,
        y,
        exog[["planted_area", "import_volume", "inventory", "weather_index"]].to_numpy(),
        ["planted_area", "import_volume", "inventory", "weather_index"],
    )
    assert supply is not None
    logy = np.log(y)
    a = MechanisticFourierForecaster(horizon=30, config=SupplyConfig(harvest_lag_months=6)).fit(
        logy, None, dates=dates, supply_daily=supply
    )
    b = MechanisticFourierForecaster(horizon=30, config=SupplyConfig(harvest_lag_months=6)).fit(
        logy, None, dates=dates, supply_daily=supply
    )
    pa = a.forecast(logy, None, len(y) - 1, float(y[-1]), 30)
    pb = b.forecast(logy, None, len(y) - 1, float(y[-1]), 30)
    assert np.allclose(pa, pb)
    assert len(pa) == 30
    assert np.all(np.isfinite(pa))


def test_walk_forward_mechanistic_finite() -> None:
    price_df, exog = _panel(n=400, seed=4)
    dates = [d.date() if hasattr(d, "date") else d for d in pd.to_datetime(price_df["date"])]
    y = price_df["value"].to_numpy(dtype=float)
    supply = build_supply_frame(
        dates,
        y,
        exog[["planted_area", "import_volume", "inventory"]].to_numpy(),
        ["planted_area", "import_volume", "inventory"],
    )
    assert supply is not None
    bt = walk_forward_mechanistic(
        dates,
        y,
        supply,
        horizon=30,
        folds=3,
        min_train=252,
        config=SupplyConfig(m_flow_window_months=6, harvest_lag_months=3),
    )
    assert bt.folds >= 1
    assert np.isfinite(bt.model_mape)
    assert np.isfinite(bt.naive_mape)


def test_pool_skips_mechanistic_without_supply() -> None:
    price_df, _ = _panel(n=320, seed=5)
    result = (
        CommodityPricePredictor(
            horizons=(30,),
            enable_gbm=False,
            enable_ou=False,
            enable_mechanistic_fourier=True,  # requested, but no drivers
        )
        .fit(price_df, commodity_code="NOSUPPLY")
        .forecast()
    )
    assert result["available"] is True
    bt = result["horizons"]["30"]["backtest"]
    assert "mechanistic_fourier_supply" not in bt["candidates"]
    assert bt["mechanistic_considered"] is False


def test_pool_includes_mechanistic_with_supply() -> None:
    price_df, exog = _panel(n=360, seed=7)
    result = (
        CommodityPricePredictor(
            horizons=(30,),
            enable_gbm=False,
            enable_ou=True,
            enable_mechanistic_fourier=None,  # auto
            supply_config=SupplyConfig(m_flow_window_months=6, harvest_lag_months=3),
        )
        .fit(price_df, exog_df=exog, commodity_code="WITHSUPPLY")
        .forecast()
    )
    assert result["available"] is True
    bt = result["horizons"]["30"]["backtest"]
    assert bt["mechanistic_considered"] is True
    assert "mechanistic_fourier_supply" in bt["candidates"]
    assert result["horizons"]["30"]["model_used"] in {
        "naive",
        "ridge_ar",
        "ou",
        "mechanistic_fourier_supply",
    }


def test_fourier_coefs_are_fold_local_not_full_series() -> None:
    """Fourier residual coeffs must be refit on ``[:cut]`` only — corrupting the
    post-cut future must not change the fold's fitted coefficients (PIT guard)."""
    price_df, exog = _panel(n=400, seed=11)
    dates = [d.date() if hasattr(d, "date") else d for d in pd.to_datetime(price_df["date"])]
    y = price_df["value"].to_numpy(dtype=float)
    supply = build_supply_frame(
        dates,
        y,
        exog[["planted_area", "import_volume", "inventory"]].to_numpy(),
        ["planted_area", "import_volume", "inventory"],
    )
    assert supply is not None
    logy = np.log(y)
    cut = 300
    clean = MechanisticFourierForecaster(
        horizon=30, config=SupplyConfig(m_flow_window_months=6, harvest_lag_months=3)
    ).fit(logy, None, end=cut, dates=dates, supply_daily=supply)
    assert clean._model is not None
    coef_clean = clean._model._residual_coef.copy()

    poisoned_y = y.copy()
    poisoned_y[cut:] = poisoned_y[cut:] * 50.0  # mangle the future only
    poisoned_logy = np.log(poisoned_y)
    poisoned_supply = supply.copy()
    poisoned_supply.loc[poisoned_supply.index[cut]:, "inventory"] = 1e6
    poisoned = MechanisticFourierForecaster(
        horizon=30, config=SupplyConfig(m_flow_window_months=6, harvest_lag_months=3)
    ).fit(poisoned_logy, None, end=cut, dates=dates, supply_daily=poisoned_supply)
    assert poisoned._model is not None
    assert np.allclose(coef_clean, poisoned._model._residual_coef)


def test_mechanistic_disabled_flag_even_with_supply() -> None:
    price_df, exog = _panel(n=320, seed=8)
    result = (
        CommodityPricePredictor(
            horizons=(30,),
            enable_gbm=False,
            enable_ou=False,
            enable_mechanistic_fourier=False,
        )
        .fit(price_df, exog_df=exog, commodity_code="OFF")
        .forecast()
    )
    bt = result["horizons"]["30"]["backtest"]
    assert bt["mechanistic_considered"] is False
    assert "mechanistic_fourier_supply" not in bt["candidates"]
