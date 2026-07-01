"""Offline tests for the Van der Pol research candidate (Phase ECON-1A).

Pin the safety contract: determinism, no future leakage, positive outputs, fail-closed
behavior, and that the candidate is NOT wired into production (`ml/forecast.py`) and does
no DB/network. These do not assert accuracy — the walk-forward backtest (rejected, see
docs/ml/econ-1a-vdp-research.md) is the accuracy evidence.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ml.models.vdp_forecaster import VdPForecaster

_REPO = Path(__file__).resolve().parents[2]


def _series(n: int = 400) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(n, dtype=float)
    logy = 0.001 * t + 0.1 * np.sin(2.0 * np.pi * t / 50.0)  # deterministic oscillating series
    return logy, np.exp(logy)


def test_deterministic_output() -> None:
    logy, vals = _series()
    f1 = VdPForecaster(horizon=30).fit(logy, None, end=350).forecast(logy, None, 349, float(vals[349]), 30)
    f2 = VdPForecaster(horizon=30).fit(logy, None, end=350).forecast(logy, None, 349, float(vals[349]), 30)
    assert np.array_equal(f1, f2)


def test_positive_outputs_and_length() -> None:
    logy, vals = _series()
    f = VdPForecaster(horizon=30).fit(logy, None, end=350).forecast(logy, None, 349, float(vals[349]), 30)
    assert f.shape == (30,) and np.all(f > 0) and np.isfinite(f).all()


def test_no_future_leakage_in_fit_boundary() -> None:
    logy, _ = _series()
    cut = 300
    a = VdPForecaster(horizon=30).fit(logy, None, end=cut)
    b = VdPForecaster(horizon=30).fit(logy[:cut].copy(), None, end=None)
    assert (a.mu_, a.w2_, a.sigma_d_, a.g_, a.degenerate_) == (b.mu_, b.w2_, b.sigma_d_, b.g_, b.degenerate_)


def test_forecast_ignores_future_values() -> None:
    logy, vals = _series()
    m = VdPForecaster(horizon=30).fit(logy, None, end=300)
    f1 = m.forecast(logy, None, 299, float(vals[299]), 30)
    perturbed = logy.copy()
    perturbed[300:] += 5.0  # corrupt the future beyond the anchor
    f2 = m.forecast(perturbed, None, 299, float(vals[299]), 30)
    assert np.array_equal(f1, f2)


def test_fail_closed_on_short_history() -> None:
    logy = np.log(np.linspace(100.0, 110.0, 40))  # far below min history
    m = VdPForecaster(horizon=30).fit(logy, None)
    assert m.degenerate_
    f = m.forecast(logy, None, len(logy) - 1, float(np.exp(logy[-1])), 30)
    assert np.allclose(f, np.exp(logy[-1]))  # flat == naive


def test_fail_closed_on_nonfinite() -> None:
    logy, _ = _series()
    bad = logy.copy()
    bad[100] = np.nan
    assert VdPForecaster(horizon=30).fit(bad, None, end=350).degenerate_


def test_not_wired_into_production() -> None:
    src = (_REPO / "ml" / "forecast.py").read_text(encoding="utf-8").lower()
    assert "vdp" not in src and "van der pol" not in src and "vdpforecaster" not in src


def test_no_db_or_network_dependency() -> None:
    src = (_REPO / "ml" / "models" / "vdp_forecaster.py").read_text(encoding="utf-8").lower()
    for tok in ("import requests", "import urllib", "psycopg", "sqlalchemy", "get_session", "import socket"):
        assert tok not in src
