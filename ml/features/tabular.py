"""Point-in-time tabular features for the autoregressive forecaster.

Every feature row at index ``i`` is built from prices at indices ``<= i`` only —
it can never read the future, which is what lets the walk-forward backtest be an
honest out-of-sample estimate (ARCHITECTURE §3.2 / CLAUDE.md §3). The features
are the levers that let a model beat the naive random-walk benchmark:

- momentum: log-returns over 1 / 5 / 20 days
- mean-reversion: deviation of today's log-price from its 20- and 60-day mean
- volatility regime: std of recent daily log-returns
- seasonality: annual day-of-year sin/cos (one harmonic)

No per-commodity logic — the same builder runs for any series (CLAUDE.md §1).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

ANNUAL = 365.25
LOOKBACK = 60  # min history (indices) before a feature row is valid

FEATURE_NAMES = (
    "intercept",
    "ret_1",
    "ret_5",
    "ret_20",
    "dev_ma20",
    "dev_ma60",
    "vol_20",
    "sin_doy",
    "cos_doy",
)


def feature_row(
    logy: np.ndarray, doy: np.ndarray, i: int, *, cycle_periods: Sequence[float] = ()
) -> np.ndarray:
    """Features at index ``i`` using only data up to and including ``i``.

    ``cycle_periods`` (in rows, from ``ml.features.cycles.detect_cycles``) append a
    sin/cos pair per multi-year cycle, evaluated at the absolute row index ``i`` so
    the model knows *where in the cycle* the anchor currently sits.
    """
    if i < LOOKBACK:
        raise ValueError(f"need >= {LOOKBACK} prior points, got index {i}")
    ma20 = float(logy[i - 19 : i + 1].mean())
    ma60 = float(logy[i - 59 : i + 1].mean())
    vol20 = float(np.std(np.diff(logy[i - 20 : i + 1])))
    angle = 2.0 * np.pi * float(doy[i]) / ANNUAL
    feats = [
        1.0,
        float(logy[i] - logy[i - 1]),
        float(logy[i] - logy[i - 5]),
        float(logy[i] - logy[i - 20]),
        float(logy[i] - ma20),
        float(logy[i] - ma60),
        vol20,
        float(np.sin(angle)),
        float(np.cos(angle)),
    ]
    for period in cycle_periods:
        a = 2.0 * np.pi * float(i) / float(period)
        feats.append(float(np.sin(a)))
        feats.append(float(np.cos(a)))
    return np.array(feats, dtype=float)


def training_matrix(
    logy: np.ndarray, doy: np.ndarray, *, horizon: int, end: int | None = None, cycle_periods: Sequence[float] = ()
) -> tuple[np.ndarray, np.ndarray]:
    """Build (X, y) where y is the ``horizon``-day-ahead log-return.

    Only rows whose target index ``i + horizon`` is strictly before ``end`` are
    included, so a caller passing ``end = cut`` gets a training set that cannot
    peek past the fold cutoff.
    """
    n = len(logy)
    stop = (n if end is None else end) - horizon
    width = len(FEATURE_NAMES) + 2 * len(cycle_periods)
    rows: list[np.ndarray] = []
    targets: list[float] = []
    for i in range(LOOKBACK, stop):
        rows.append(feature_row(logy, doy, i, cycle_periods=cycle_periods))
        targets.append(float(logy[i + horizon] - logy[i]))
    if not rows:
        return np.empty((0, width)), np.empty(0)
    return np.vstack(rows), np.array(targets, dtype=float)
