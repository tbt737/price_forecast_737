"""Data-driven multi-year cycle detection (the "Cobweb" / structural cycle).

Agricultural and many commodity prices carry a low-frequency boom-bust cycle of
several years that repeats roughly but never identically — driven by the
supply-response lag (high price -> growers plant more -> glut -> crash -> plant
less -> shortage -> spike), largely independent of short-term financial flows.

``detect_cycles`` extracts the dominant multi-year period(s) of a single series
from its own history by FFT on the detrended log-price. It is **point-in-time**:
pass only the training slice. Periods are returned in *rows* (the series' own
sampling), so the harmonic ``sin(2*pi*i/period)`` is sampling-agnostic — no need
to reconcile trading days vs calendar days. Each commodity (and each region's
series) therefore gets its own cycle, exactly as the structure differs by
territory.
"""

from __future__ import annotations

import numpy as np

MIN_YEARS = 6.0  # need a few cycles before a multi-year period is trustworthy


def detect_cycles(
    logy: np.ndarray, *, rows_per_year: float, n: int = 2, lo_years: float = 1.5, hi_years: float = 7.0
) -> list[float]:
    """Up to ``n`` dominant cycle periods (in rows) within [lo_years, hi_years].

    Returns ``[]`` when the history is too short to trust a multi-year cycle.
    """
    y = np.asarray(logy, dtype=float)
    m = len(y)
    total_years = m / max(1e-9, rows_per_year)
    if m < 64 or total_years < MIN_YEARS:
        return []
    hi = min(hi_years, total_years / 2.0)  # need >= 2 repetitions to claim a period
    if hi <= lo_years:
        return []

    t = np.arange(m, dtype=float)
    detrended = y - np.polyval(np.polyfit(t, y, 1), t)
    power = np.abs(np.fft.rfft(detrended * np.hanning(m))) ** 2
    freq = np.fft.rfftfreq(m, d=1.0)  # cycles per row

    lo_rows, hi_rows = lo_years * rows_per_year, hi * rows_per_year
    sep = 0.4 * rows_per_year  # keep detected periods apart by ~0.4yr
    out: list[float] = []
    for i in np.argsort(power)[::-1]:
        if freq[i] <= 0.0:
            continue
        period = 1.0 / float(freq[i])
        if lo_rows <= period <= hi_rows and all(abs(period - q) > sep for q in out):
            out.append(period)
        if len(out) >= n:
            break
    return out
