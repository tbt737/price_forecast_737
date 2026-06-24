"""Deterministic trend + annual Fourier design matrix.

``t`` is a calendar-day index (days since the series start), so the harmonics
capture the true annual cycle even though trading days skip weekends.
"""

from __future__ import annotations

import numpy as np

ANNUAL = 365.25


def design_matrix(t: np.ndarray, *, harmonics: int = 3, period: float = ANNUAL) -> np.ndarray:
    """Columns: [intercept, linear trend (in years), sin/cos annual harmonics]."""
    ts = np.asarray(t, dtype=float)
    columns: list[np.ndarray] = [np.ones_like(ts), ts / period]
    for k in range(1, harmonics + 1):
        angle = 2.0 * np.pi * k * ts / period
        columns.append(np.sin(angle))
        columns.append(np.cos(angle))
    return np.column_stack(columns)
