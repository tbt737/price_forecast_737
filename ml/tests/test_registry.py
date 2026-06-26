"""Tests for the internal model registry (Phase 7A)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from ml.backtests.walk_forward import BacktestResult
from ml.registry.core import REGISTRY_DIR, find_best_model, load_latest_model, register_model


def test_registry_module_import_does_not_create_default_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ml.registry.core.REGISTRY_DIR", tmp_path / "should_not_exist")

    for name in list(sys.modules):
        if name.startswith("ml.registry"):
            del importlib.sys.modules[name]

    importlib.import_module("ml.registry.core")
    assert not (tmp_path / "should_not_exist").exists()


def test_register_and_load_round_trip(tmp_path: Path) -> None:
    backtest = BacktestResult(horizon=5, folds=4, model_mape=2.5, model_rmse=1.1, naive_mape=3.0)
    register_model(
        commodity_code="ROBUSTA",
        model_code="sarimax",
        family="statsmodels",
        horizon="weekly",
        features_used=["target_price", "macro_a"],
        hyperparameters={"folds": 4},
        backtest=backtest,
        registry_dir=tmp_path,
        allow_write=True,
        trained_at="2026-06-01T12:00:00Z",
    )

    loaded = load_latest_model("ROBUSTA", "sarimax", registry_dir=tmp_path)
    assert loaded is not None
    assert loaded.features_used == ["target_price", "macro_a"]
    assert loaded.backtest.model_mape == 2.5


def test_find_best_model_prefers_lower_mape(tmp_path: Path) -> None:
    good = BacktestResult(horizon=5, folds=4, model_mape=2.0, model_rmse=1.0, naive_mape=4.0)
    worse = BacktestResult(horizon=5, folds=4, model_mape=3.0, model_rmse=1.0, naive_mape=4.0)
    register_model(
        "ROBUSTA",
        "model_a",
        "statsmodels",
        "weekly",
        ["target_price"],
        {},
        worse,
        registry_dir=tmp_path,
        allow_write=True,
        trained_at="2026-06-01T12:00:00Z",
    )
    register_model(
        "ROBUSTA",
        "model_b",
        "statsmodels",
        "weekly",
        ["target_price"],
        {},
        good,
        registry_dir=tmp_path,
        allow_write=True,
        trained_at="2026-06-01T12:00:00Z",
    )

    best = find_best_model("ROBUSTA", registry_dir=tmp_path)
    assert best is not None
    assert best.model_code == "model_b"


def test_default_registry_dir_is_not_created_on_import() -> None:
    # REGISTRY_DIR may exist from prior local runs; import must not force-create it.
    import ml.registry.core as core

    assert core.REGISTRY_DIR == REGISTRY_DIR