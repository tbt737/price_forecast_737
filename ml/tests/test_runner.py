"""Tests for the guarded internal ML runner (Phase 7A)."""

from __future__ import annotations

import importlib
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from ml.backtests.walk_forward import BacktestResult
from ml.registry.core import register_model
from ml.runner import (
    ForecastRunner,
    InsufficientHistoryError,
    InvalidHorizonError,
    MissingDataError,
    PriceSeriesData,
    RunnerConfig,
    run_model_backtest,
)


def _synthetic_series(n: int = 500) -> PriceSeriesData:
    rng = np.random.default_rng(42)
    values = np.exp(np.cumsum(rng.normal(0, 0.01, n)) + np.log(100.0))
    start = date(2020, 1, 1)
    dates = [start + timedelta(days=i) for i in range(n)]
    exog = rng.normal(0, 1, (n, 2))
    return PriceSeriesData(
        dates=dates,
        values=values,
        feature_names=["target_price", "macro_a", "macro_b"],
        exog_features=exog,
    )


def test_runner_module_import_has_no_db_or_network_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("import-time DB/network call detected")

    monkeypatch.setitem(sys.modules, "app.db.session", type(sys)("app.db.session"))
    sys.modules["app.db.session"].get_session_factory = _boom  # type: ignore[attr-defined]

    for name in list(sys.modules):
        if name.startswith("ml.runner") or name.startswith("ml.registry"):
            del sys.modules[name]

    importlib.import_module("ml.runner")


def test_runner_dry_run_default_does_not_write_registry(tmp_path: Path) -> None:
    data = _synthetic_series()
    config = RunnerConfig(
        commodity_code="ROBUSTA",
        model_code="sarimax",
        dry_run=True,
        allow_registry_write=False,
        registry_dir=tmp_path,
        min_history=300,
    )
    result = run_model_backtest(
        data,
        {"model_code": "sarimax", "family": "statsmodels", "horizon": "weekly"},
        config,
    )
    assert result.dry_run is True
    assert result.registered is False
    assert list(tmp_path.glob("*.json")) == []


def test_runner_registry_write_requires_explicit_flag(tmp_path: Path) -> None:
    backtest = BacktestResult(horizon=5, folds=3, model_mape=1.0, model_rmse=1.0, naive_mape=5.0)
    metadata = register_model(
        commodity_code="TEST",
        model_code="unit_model",
        family="statsmodels",
        horizon="weekly",
        features_used=["target_price"],
        hyperparameters={"folds": 3},
        backtest=backtest,
        registry_dir=tmp_path,
        allow_write=False,
        trained_at="2026-01-01T00:00:00Z",
    )
    assert list(tmp_path.glob("*.json")) == []
    assert metadata.version == 1

    register_model(
        commodity_code="TEST",
        model_code="unit_model",
        family="statsmodels",
        horizon="weekly",
        features_used=["target_price"],
        hyperparameters={"folds": 3},
        backtest=backtest,
        registry_dir=tmp_path,
        allow_write=True,
        trained_at="2026-01-01T00:00:00Z",
    )
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


def test_runner_fails_closed_on_insufficient_history() -> None:
    data = _synthetic_series(n=50)
    config = RunnerConfig(commodity_code="ROBUSTA", model_code="sarimax", min_history=300)
    with pytest.raises(InsufficientHistoryError):
        run_model_backtest(
            data,
            {"model_code": "sarimax", "family": "statsmodels", "horizon": "weekly"},
            config,
        )


def test_runner_fails_closed_on_invalid_horizon() -> None:
    data = _synthetic_series()
    config = RunnerConfig(commodity_code="ROBUSTA", model_code="sarimax")
    with pytest.raises(InvalidHorizonError):
        run_model_backtest(
            data,
            {"model_code": "bad", "family": "statsmodels", "horizon": "quarterly"},
            config,
        )


def test_runner_requires_data_or_session() -> None:
    runner = ForecastRunner(session=None)
    config = RunnerConfig(commodity_code="ROBUSTA", model_code="sarimax")
    with pytest.raises(MissingDataError):
        runner.run(config)


def test_runner_deterministic_repeated_runs() -> None:
    data = _synthetic_series()
    config = RunnerConfig(commodity_code="ROBUSTA", model_code="sarimax", min_history=300)
    model_entry = {"model_code": "sarimax", "family": "statsmodels", "horizon": "weekly"}
    first = run_model_backtest(data, model_entry, config)
    second = run_model_backtest(data, model_entry, config)
    assert first.metrics == second.metrics
    assert first.backtest.model_mape == second.backtest.model_mape
    assert first.feature_names == second.feature_names


def test_runner_metadata_completeness() -> None:
    data = _synthetic_series()
    config = RunnerConfig(commodity_code="ROBUSTA", model_code="sarimax", min_history=300)
    result = run_model_backtest(
        data,
        {"model_code": "sarimax", "family": "statsmodels", "horizon": "weekly"},
        config,
    )
    meta = result.to_metadata_dict()
    assert meta["model_type"] == "statsmodels"
    assert meta["horizon"] == "weekly"
    assert meta["horizon_days"] == 5
    assert meta["training_window"]["observations"] >= 300
    assert meta["feature_count"] == len(meta["feature_names"])
    assert set(meta["metrics"]) >= {"model_mape", "model_rmse", "naive_mape", "beats_naive", "folds"}
    assert "fallback_used" in meta


def test_allow_registry_write_requires_no_dry_run() -> None:
    with pytest.raises(ValueError, match="allow_registry_write requires dry_run=False"):
        RunnerConfig(commodity_code="ROBUSTA", dry_run=True, allow_registry_write=True)