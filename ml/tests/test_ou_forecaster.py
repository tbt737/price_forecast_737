"""Unit tests for the Phase 8A OU / damped mean-reversion forecaster.

Guards (CLAUDE.md §3): determinism, point-in-time (no look-ahead) trend, fail-closed
on bad/short input, no input mutation, the restoring-force behaviour, and that OU
never bypasses the naive benchmark in the research best-of pool.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from ml.backtests.research_pool import best_of
from ml.backtests.walk_forward import walk_forward_ou
from ml.models.ou_forecaster import OUForecaster, causal_trailing_mean


def _doy(n: int) -> np.ndarray:
    return np.array([(i % 365) + 1 for i in range(n)], dtype=float)


# ── point-in-time correctness ────────────────────────────────────────────────
def test_causal_trailing_mean_ignores_the_future() -> None:
    x = np.log(np.linspace(100.0, 130.0, 200))
    base = causal_trailing_mean(x, 30)
    corrupted = x.copy()
    corrupted[120:] = -999.0  # mangle everything after index 119
    after = causal_trailing_mean(corrupted, 30)
    assert np.allclose(base[:120], after[:120])  # past values unaffected by the future


def test_ou_fit_does_not_peek_past_end() -> None:
    rng = np.random.default_rng(4)
    logy = np.cumsum(rng.normal(0, 0.01, 500)) + np.log(100.0)
    end = 300
    a = OUForecaster(horizon=30, trend_span=60).fit(logy, None, end=end)
    corrupt = logy.copy()
    corrupt[end:] = -999.0  # future garbage
    b = OUForecaster(horizon=30, trend_span=60).fit(corrupt, None, end=end)
    assert a.phi_ == b.phi_ and a.g_ == b.g_  # fit used only data before `end`


def test_ou_forecast_invariant_to_values_after_anchor() -> None:
    rng = np.random.default_rng(8)
    logy = np.cumsum(rng.normal(0, 0.01, 500)) + np.log(100.0)
    anchor = 399
    model = OUForecaster(horizon=30, trend_span=60).fit(logy, None, end=anchor + 1)
    f1 = model.forecast(logy, None, anchor, float(np.exp(logy[anchor])), 30)
    corrupt = logy.copy()
    corrupt[anchor + 1 :] = 12.0  # future cannot influence an anchored forecast
    f2 = model.forecast(corrupt, None, anchor, float(np.exp(logy[anchor])), 30)
    assert np.allclose(f1, f2)


# ── determinism ──────────────────────────────────────────────────────────────
def test_ou_is_deterministic() -> None:
    rng = np.random.default_rng(7)
    logy = np.cumsum(rng.normal(0, 0.01, 400)) + np.log(100.0)
    a = OUForecaster(horizon=30).fit(logy, None)
    b = OUForecaster(horizon=30).fit(logy, None)
    assert a.phi_ == b.phi_ and a.g_ == b.g_
    fa = a.forecast(logy, None, 399, 100.0, 30)
    fb = b.forecast(logy, None, 399, 100.0, 30)
    assert np.array_equal(fa, fb)  # closed form ⇒ bit-for-bit identical


# ── fail-closed ──────────────────────────────────────────────────────────────
def test_ou_fails_closed_on_short_history() -> None:
    logy = np.log(np.linspace(100.0, 110.0, 50))  # shorter than trend_span+horizon
    model = OUForecaster(horizon=30, trend_span=90).fit(logy, None)
    assert model.degenerate_ is True
    traj = model.forecast(logy, None, 49, 110.0, 5)
    assert np.allclose(traj, 110.0)  # flat == naive


def test_ou_rejects_nonfinite_logprice() -> None:
    # A non-positive price upstream yields a non-finite log ⇒ fail closed.
    prices = np.linspace(100.0, 130.0, 400).copy()
    prices[200] = -5.0  # non-positive
    with np.errstate(invalid="ignore", divide="ignore"):
        logy = np.log(prices)  # -> nan/-inf at index 200
    model = OUForecaster(horizon=30, trend_span=60).fit(logy, None)
    assert model.degenerate_ is True
    assert np.allclose(model.forecast(logy, None, 399, 130.0, 5), 130.0)


# ── no input mutation ────────────────────────────────────────────────────────
def test_ou_does_not_mutate_input() -> None:
    rng = np.random.default_rng(2)
    logy = np.cumsum(rng.normal(0, 0.01, 400)) + np.log(100.0)
    snapshot = logy.copy()
    model = OUForecaster(horizon=30).fit(logy, None)
    model.forecast(logy, None, 399, 100.0, 30)
    assert np.array_equal(logy, snapshot)  # fit/forecast never write into the input


# ── restoring force ──────────────────────────────────────────────────────────
def test_ou_pulls_above_trend_price_back_down() -> None:
    base = np.full(300, np.log(100.0))
    base[-1] = np.log(115.0)  # last price sits above the slow trend
    model = OUForecaster(horizon=30, trend_span=30, trend_damping=0.97).fit(base, None)
    traj = model.forecast(base, None, 299, 115.0, 10)
    assert traj[0] < 115.0  # restoring force drags it back toward the trend
    assert traj[-1] <= traj[0]  # and keeps reverting (monotone toward trend)


def test_ou_estimates_reversion_speed_on_ar1_series() -> None:
    rng = np.random.default_rng(3)
    n = 1500
    d = np.zeros(n)
    for t in range(1, n):
        d[t] = 0.8 * d[t - 1] + rng.normal(0, 0.02)  # AR(1) deviation, true phi = 0.8
    logy = np.log(100.0) + d
    model = OUForecaster(horizon=30, trend_span=90).fit(logy, None)
    assert 0.5 < model.phi_ < 0.95  # recovers a mean-reverting (not unit-root) persistence


# ── does not bypass the naive benchmark ──────────────────────────────────────
def test_best_of_keeps_naive_when_ou_is_worse() -> None:
    # OU worse than naive ⇒ best-of must stay on naive (margin rule intact).
    choice, mape = best_of({"ridge_ar": 9.0, "ou": 10.0}, naive_mape=8.0)
    assert choice == "naive" and mape == 8.0


def test_best_of_picks_ou_only_when_it_clears_the_margin() -> None:
    # OU must beat naive by SWITCH_MARGIN (2%) to displace it.
    assert best_of({"ou": 7.99}, naive_mape=8.0)[0] == "naive"  # 0.1% < 2% margin
    assert best_of({"ou": 7.0}, naive_mape=8.0)[0] == "ou"  # clears the margin


# ── walk-forward integration ─────────────────────────────────────────────────
def test_walk_forward_ou_produces_finite_folds() -> None:
    n = 600
    rng = np.random.default_rng(5)
    values = np.exp(np.cumsum(rng.normal(0, 0.01, n)) + np.log(100.0))
    start = date(2020, 1, 1)
    dates = [start + timedelta(days=i) for i in range(n)]
    bt = walk_forward_ou(dates, values, horizon=20, min_train=252)
    assert bt.folds > 0
    assert np.isfinite(bt.model_mape) and np.isfinite(bt.naive_mape)
