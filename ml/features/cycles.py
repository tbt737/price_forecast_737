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


def _stable_subset(
    logy: np.ndarray, periods: list[float], *, frac: float = 0.4, recent_frac: float = 0.25
) -> list[float]:
    """Phase 4 (full) — keep only recurring, still-active cycles via a Morlet
    continuous-wavelet scalogram.

    A cycle is kept only if its scale stands out (top third of the scalogram column)
    in >= ``frac`` of the timeline AND in >= ``frac`` of the most recent
    ``recent_frac`` — a cycle that faded long ago must not drive a near-term forecast
    ("no spring is identical"). One scalogram is built per call (covering every
    candidate) on a decimated signal, so it stays cheap. Falls back to a per-window
    STFT check if pywt is unavailable."""
    if not periods:
        return []
    try:
        import pywt
    except Exception:
        return [p for p in periods if _rolling_window_stable(logy, p)]

    m = len(logy)
    step = max(1, m // 1500)  # decimate long series; multi-row cycles survive
    sig0 = logy[::step]
    n = len(sig0)
    if n < 64:
        return periods
    t = np.arange(n, dtype=float)
    sig = sig0 - np.polyval(np.polyfit(t, sig0, 1), t)
    dperiods = [p / step for p in periods]
    lo, hi = max(6.0, 0.4 * min(dperiods)), min(n / 2.0, 2.5 * max(dperiods))
    if hi <= lo:
        return periods
    scales = np.geomspace(lo, hi, 18)  # central_freq(cmor1.5-1.0)=1.0 ⇒ scale≈period
    coef, _ = pywt.cwt(sig, scales, "cmor1.5-1.0", sampling_period=1.0)
    power = np.abs(coef) ** 2  # [n_scales, n]
    col_thresh = np.quantile(power, 0.67, axis=0)
    cut = int(n * (1.0 - recent_frac))
    kept: list[float] = []
    for period, dp in zip(periods, dperiods, strict=True):
        present = power[int(np.argmin(np.abs(scales - dp)))] >= col_thresh
        if present.mean() >= frac and present[cut:].mean() >= frac:
            kept.append(period)
    return kept


def _rolling_window_stable(logy: np.ndarray, period: float, *, frac: float = 0.5) -> bool:
    """STFT fallback (pywt absent): the period must stand out in >= ``frac`` of
    windows ~3 cycles long AND in the most recent window. Too few windows ⇒ kept."""
    m = len(logy)
    wlen = int(3.0 * period)
    if wlen < 48 or m < 2 * wlen:
        return True
    nwin = m // wlen
    if nwin < 2:
        return True
    target_f = 1.0 / period
    win_hit: list[bool] = []
    for w in range(nwin):
        seg = logy[w * wlen : (w + 1) * wlen]
        tt = np.arange(len(seg), dtype=float)
        seg = seg - np.polyval(np.polyfit(tt, seg, 1), tt)
        power = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        freq = np.fft.rfftfreq(len(seg), d=1.0)
        band = (freq > 0.5 * target_f) & (freq < 1.5 * target_f)
        win_hit.append(bool(band.any() and power[band].max() >= np.quantile(power[1:], 0.67)))
    return sum(win_hit) >= max(1, int(round(frac * nwin))) and win_hit[-1]


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
    for period in candidates:  # Phase 3: predictive (linear R^2 of the harmonic)
        a = 2.0 * np.pi * idx / period
        x = np.column_stack([ones, np.sin(a), np.cos(a)])
        beta, *_ = np.linalg.lstsq(x, fut, rcond=None)
        r2 = 1.0 - float(np.sum((fut - x @ beta) ** 2)) / ss_tot
        if r2 >= MIN_R2:
            scored.append((period, r2))
    # Phase 4: keep only recurring + still-active cycles (one wavelet scalogram).
    stable = set(_stable_subset(logy[:m], [p for p, _ in scored]))
    scored = [(p, r2) for p, r2 in scored if p in stable]
    scored.sort(key=lambda s: s[1], reverse=True)
    return [p for p, _ in scored[:max_keep]]
