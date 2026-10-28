"""Calendar density used for cycle selection must ignore future observations."""

from datetime import date, timedelta

import numpy as np
import pytest

import ml.backtests.walk_forward as wf


def test_cycle_sampling_density_ignores_future_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    n, cut = 300, 252
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    changed = dates[:cut] + [dates[cut - 1] + timedelta(days=30 * (i + 1)) for i in range(n - cut)]
    values = np.linspace(100.0, 120.0, n)
    densities: list[float] = []

    def cycles(*args: object, rows_per_year: float, **kwargs: object) -> list[float]:
        densities.append(rows_per_year)
        return []

    class FlatModel:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fit(self, *args: object, **kwargs: object) -> "FlatModel":
            return self

        def forecast(
            self, logy: np.ndarray, doy: np.ndarray, anchor_idx: int, y_anchor: float, steps: int, **kwargs: object
        ) -> np.ndarray:
            return np.full(steps, y_anchor)

    monkeypatch.setattr(wf, "select_cycles", cycles)
    monkeypatch.setattr(wf, "GBMForecaster", FlatModel)
    for calendar in (dates, changed):
        result = wf.walk_forward_gbm(calendar, values, horizon=10, folds=1, min_train=cut, use_cycles=True)
        assert result.folds == 1
    assert densities[0] == pytest.approx(cut / ((dates[cut - 1] - dates[0]).days / 365.25))
    assert densities[0] == densities[1]
