"""Multi-scale price-cycle search (Phases 1-3 of the cycle-search plan).

Goal: find, per commodity/region, the *right* cycle(s) to forecast with — where
"right" is decided by out-of-sample improvement, not by a pretty spectral peak.

- Phase 1 (multi-scale): search the whole period range, from ~1 month (e.g. the
  onion storage/arrival rhythm) through the annual season up to multi-year
  super-cycles. The earlier detector only looked at 1.5-7 years and missed short
  cycles entirely.
- Phase 2 (two detectors): propose candidate periods from BOTH the FFT power
  spectrum (sinusoidal cycles) and the autocorrelation function (handles
  non-sinusoidal / saw-tooth Cobweb cycles, and reversals).
- Phase 3 (backtest filter): keep a candidate only if adding its harmonic reduces
  error on an inner hold-out — the honest arbiter. Everything is point-in-time:
  callers pass ``end`` and only data before it is ever used.

Periods are in *rows* (the series' own sampling), so ``sin(2*pi*i/period)`` is
sampling-agnostic across trading-day vs near-daily series.
"""

from __future__ import annotations

import numpy as np

LO_DAYS = 30.0  # shortest cycle searched (~1 month)
HI_YEARS = 8.0  # longest cycle searched (commodity super-cycle)
MIN_YEARS = 1.5  # need at least this much history to propose anything


def propose_cycles(
    logy: np.ndarray, *, rows_per_year: float, n: int = 4, lo_days: float = LO_DAYS, hi_years: float = HI_YEARS
) -> list[float]:
    """Phase 1+2 — candidate periods (rows) across all scales, from FFT + ACF peaks."""
    y = np.asarray(logy, dtype=float)
    m = len(y)
    if m < 90 or m / max(1e-9, rows_per_year) < MIN_YEARS:
        return []
    t = np.arange(m, dtype=float)
    detrended = y - np.polyval(np.polyfit(t, y, 1), t)
    lo_rows = max(2.0, lo_days)
    hi_rows = min(hi_years * rows_per_year, m / 2.0)  # need >= 2 repetitions
    if hi_rows <= lo_rows:
        return []

    scored: list[tuple[float, float]] = []  # (period_rows, score in [0,1])

    # FFT power spectrum
    power = np.abs(np.fft.rfft(detrended * np.hanning(m))) ** 2
    freq = np.fft.rfftfreq(m, d=1.0)
    fmax = float(power[1:].max()) if m > 2 else 1.0
    for i in np.argsort(power)[::-1][1:60]:
        if freq[i] <= 0:
            continue
        period = 1.0 / float(freq[i])
        if lo_rows <= period <= hi_rows:
            scored.append((period, float(power[i]) / max(fmax, 1e-12)))

    # Autocorrelation peaks (non-sinusoidal cycles, reversals)
    centred = detrended - detrended.mean()
    ac = np.correlate(centred, centred, "full")[m - 1 :]
    ac = ac / max(ac[0], 1e-12)
    hi_lag = int(min(hi_rows, m - 2))
    for lag in range(int(lo_rows), hi_lag):
        if ac[lag] > ac[lag - 1] and ac[lag] > ac[lag + 1] and ac[lag] > 0.10:
            scored.append((float(lag), float(ac[lag])))

    # Merge: dedup periods within 15%, keep the higher score; rank; take top n.
    scored.sort(key=lambda s: s[1], reverse=True)
    kept: list[float] = []
    for period, _ in scored:
        if all(abs(period - q) > 0.15 * q for q in kept):
            kept.append(period)
        if len(kept) >= n:
            break
    return kept


MIN_R2 = 0.006  # a cycle must explain >=0.6% of the h-ahead return variance to be kept


def _is_stable(logy: np.ndarray, period: float, *, frac: float = 0.5) -> bool:
    """Phase 4 (light) — is ``period`` a recurring peak, not a one-off?

    Rolling-window spectrogram: split the history into windows ~3 cycles long and
    require the period to stand out (power in the top third of its window's band)
    in at least ``frac`` of them. Too few windows to judge ⇒ not rejected ("no
    spring is identical" — we only drop cycles that clearly appear once)."""
    m = len(logy)
    wlen = int(3.0 * period)
    if wlen < 48 or m < 2 * wlen:
        return True
    nwin = m // wlen
    if nwin < 2:
        return True
    target_f = 1.0 / period
    hits = 0
    for w in range(nwin):
        seg = logy[w * wlen : (w + 1) * wlen]
        tt = np.arange(len(seg), dtype=float)
        seg = seg - np.polyval(np.polyfit(tt, seg, 1), tt)
        power = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        freq = np.fft.rfftfreq(len(seg), d=1.0)
        band = (freq > 0.5 * target_f) & (freq < 1.5 * target_f)  # near the candidate period
        if not band.any():
            continue
        if power[band].max() >= np.quantile(power[1:], 0.67):  # stands out vs the window's spectrum
            hits += 1
    return hits >= max(1, int(round(frac * nwin)))


def select_cycles(
    logy: np.ndarray,
    doy: np.ndarray,
    *,
    rows_per_year: float,
    horizon: int,
    end: int | None = None,
    max_keep: int = 3,
) -> list[float]:
    """Phase 3 — keep candidate cycles whose harmonic actually predicts the
    ``horizon``-ahead return in-window (cheap linear R^2 filter).

    Point-in-time: only ``logy[:end]`` is used. This is a fast pre-filter; the
    final honest arbiter is still the outer walk-forward (gbm_cyc must beat the
    plain models by a margin to be chosen). The linear filter keeps it ~O(ms) so
    the per-fold backtest stays affordable."""
    from ml.features.tabular import LOOKBACK

    m = end if end is not None else len(logy)
    candidates = propose_cycles(logy[:m], rows_per_year=rows_per_year)
    if not candidates:
        return []
    idx = np.arange(LOOKBACK, m - horizon)
    if len(idx) < 100:
        return candidates[:max_keep]

    fut = logy[idx + horizon] - logy[idx]
    fut = fut - fut.mean()
    ss_tot = float(np.sum(fut**2))
    if ss_tot <= 0:
        return []
    ones = np.ones_like(fut)
    scored: list[tuple[float, float]] = []
    for period in candidates:
        a = 2.0 * np.pi * idx / period
        x = np.column_stack([ones, np.sin(a), np.cos(a)])
        beta, *_ = np.linalg.lstsq(x, fut, rcond=None)
        r2 = 1.0 - float(np.sum((fut - x @ beta) ** 2)) / ss_tot
        if r2 >= MIN_R2 and _is_stable(logy[:m], period):  # predictive AND recurring
            scored.append((period, r2))
    scored.sort(key=lambda s: s[1], reverse=True)
    return [p for p, _ in scored[:max_keep]]
