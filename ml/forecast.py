"""Forecast orchestrator: load a real price series, fit the baseline, forecast
30/90 trading days ahead with an ~80% band, and attach an honest walk-forward
backtest. No per-commodity logic — works for any commodity that has prices.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

_API_DIR = Path(__file__).resolve().parent.parent / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from app.models import DimCommodity, DimMarketInstrument, FactPriceDaily  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from ml.backtests.walk_forward import walk_forward_ar, walk_forward_gbm, walk_forward_ou  # noqa: E402
from ml.features.cycles import select_cycles  # noqa: E402
from ml.models.gbm_forecaster import GBMForecaster  # noqa: E402
from ml.models.gbm_forecaster import is_available as gbm_available  # noqa: E402
from ml.models.ou_forecaster import OUForecaster  # noqa: E402
from ml.models.ridge_forecaster import RidgeARForecaster  # noqa: E402

MIN_HISTORY = 252  # ~1 trading year required to fit the model
Z_80 = 1.2816  # ~80% normal band half-width
SWITCH_MARGIN = 0.02  # require >=2% relative MAPE improvement to leave the naive benchmark
OU_ENABLED = True  # Phase 8B: include the OU mean-reversion candidate in the pool (still gated by the margin rule)


def select_candidate(
    candidates: dict[str, float], naive_mape: float, *, margin: float = SWITCH_MARGIN
) -> tuple[str, float]:
    """Best-of selection (Phase 7A rule, unchanged): the lowest finite-MAPE candidate
    wins, but only displaces the naive benchmark when it beats it by ``margin``. This
    guards against crowning a noise-level "winner" out of several candidates — and is
    exactly what keeps a weak OU from ever being chosen. Returns ``(model_used,
    chosen_mape)``; ``model_used == "naive"`` means the benchmark held."""
    finite = {k: v for k, v in candidates.items() if np.isfinite(v)}
    best = min(finite, key=lambda k: finite[k]) if finite else None
    if best is not None and np.isfinite(naive_mape) and finite[best] < naive_mape * (1.0 - margin):
        return best, finite[best]
    return "naive", (finite[best] if best is not None else float("nan"))


def _next_business_days(last: date, count: int) -> list[date]:
    out: list[date] = []
    cursor = last
    while len(out) < count:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:  # Mon–Fri
            out.append(cursor)
    return out


def load_price_series(session: Session, commodity_code: str) -> dict[str, Any] | None:
    commodity = session.execute(
        select(DimCommodity).filter_by(commodity_code=commodity_code.upper())
    ).scalar_one_or_none()
    if commodity is None:
        return None
    instrument_key = session.execute(
        select(FactPriceDaily.market_instrument_key)
        .where(FactPriceDaily.commodity_key == commodity.commodity_key)
        .group_by(FactPriceDaily.market_instrument_key)
        .order_by(func.count().desc())
        .limit(1)
    ).scalar_one_or_none()
    if instrument_key is None:
        return {"commodity": commodity, "instrument": None, "dates": [], "values": []}

    instrument = session.get(DimMarketInstrument, instrument_key)
    rows = session.execute(
        select(FactPriceDaily.price_date, FactPriceDaily.value)
        .where(
            FactPriceDaily.commodity_key == commodity.commodity_key,
            FactPriceDaily.market_instrument_key == instrument_key,
            FactPriceDaily.value.is_not(None),
        )
        .order_by(FactPriceDaily.price_date)
    ).all()
    return {
        "commodity": commodity,
        "instrument": instrument,
        "dates": [r.price_date for r in rows],
        "values": [float(r.value) for r in rows],
    }


def _naive_interval(y_anchor: float, ret_sigma: float, steps: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flat last-value forecast with a random-walk band (the conservative fallback)."""
    point = np.repeat(float(y_anchor), steps)
    s = np.arange(1, steps + 1)
    band = Z_80 * ret_sigma * np.sqrt(s)
    return point, point * np.exp(-band), point * np.exp(band)


def forecast_commodity(
    session: Session,
    commodity_code: str,
    *,
    horizons: tuple[int, ...] = (30, 90),
    l2: float = 5.0,
    enable_ou: bool = OU_ENABLED,
) -> dict[str, Any]:
    loaded = load_price_series(session, commodity_code)
    if loaded is None:
        return {"available": False, "reason": "unknown commodity", "commodity_code": commodity_code.upper()}

    commodity = loaded["commodity"]
    instrument = loaded["instrument"]
    dates: list[date] = loaded["dates"]
    values: list[float] = loaded["values"]
    base: dict[str, Any] = {
        "commodity_code": commodity.commodity_code,
        "instrument_code": instrument.instrument_code if instrument else None,
        "currency": instrument.currency if instrument else None,
        "model": "ridge_ar",  # Ridge autoregressive; falls back to naive where it can't beat it
    }
    # drop non-positive prices (e.g. the 2020 negative-oil episode) before log-fitting
    clean = [(d, v) for d, v in zip(dates, values, strict=True) if v > 0]
    dates = [c[0] for c in clean]
    values = [c[1] for c in clean]
    if len(values) < MIN_HISTORY:
        return {**base, "available": False, "reason": f"need >= {MIN_HISTORY} positive prices, have {len(values)}"}

    y = np.array(values, dtype=float)
    logy = np.log(y)
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)

    import pandas as pd
    from sqlalchemy import text

    view_query = text("SELECT * FROM mv_ml_daily_features_wide WHERE commodity_key = :key ORDER BY as_of_date")
    res = session.execute(view_query, {"key": commodity.commodity_key})
    data = res.fetchall()
    if data:
        cols = list(res.keys())
        df_view = pd.DataFrame(data, columns=cols)
        df_view['as_of_date'] = pd.to_datetime(df_view['as_of_date']).dt.date
        df_view = df_view.set_index('as_of_date')
        drop_cols = [c for c in ["commodity_key", "price_close"] if c in df_view.columns]
        df_view = df_view.drop(columns=drop_cols)

        import logging
        logger = logging.getLogger(__name__)

        for c in df_view.columns:
            # apply numeric coercion only to feature columns
            df_view[c] = pd.to_numeric(df_view[c], errors="coerce")

        # Drop columns that are completely NaN after coercion
        nan_cols = df_view.columns[df_view.isna().all()].tolist()
        if nan_cols:
            logger.warning(f"Dropping columns due to non-numeric garbage: {nan_cols}")
            df_view = df_view.drop(columns=nan_cols)

        # time-safe imputation
        df_view = df_view.sort_index()
        df_view = df_view.ffill()
        df_view = df_view.reindex(dates, method="ffill")

        # train-only median/imputer substitute (using past available data)
        df_view = df_view.fillna(df_view.median()).fillna(0.0)

        exog_feature_names = df_view.columns.tolist()
        logger.info(f"Final exog_feature_names passed to model: {exog_feature_names}")
        exog_features = df_view.values
    else:
        exog_features = np.empty((len(dates), 0))
    ret_sigma = float(np.std(np.diff(logy), ddof=1)) if len(logy) > 1 else 0.0
    anchor_idx = len(values) - 1
    y_anchor = float(values[-1])
    span_days = max(1, (dates[-1] - dates[0]).days)
    rpy = len(values) / (span_days / 365.25)  # rows per year (for cycle scales)

    horizon_out: dict[str, Any] = {}
    for h in horizons:
        future_dates = _next_business_days(dates[-1], h)

        # Backtest every candidate out-of-sample; the naive MAPE is the bar to beat.
        ar = walk_forward_ar(dates, y, horizon=h, l2=l2, exog_features=exog_features)
        naive_mape = ar.naive_mape
        candidates: dict[str, float] = {"ridge_ar": ar.model_mape}
        builders: dict[str, Any] = {
            "ridge_ar": lambda hh=h: RidgeARForecaster(horizon=hh, l2=l2).fit(
                logy, doy, exog_features=exog_features
            )
        }
        if gbm_available():
            gb = walk_forward_gbm(dates, y, horizon=h, exog_features=exog_features)
            candidates["gbm"] = gb.model_mape
            builders["gbm"] = lambda hh=h: GBMForecaster(horizon=hh).fit(logy, doy, exog_features=exog_features)
            # Cycle-augmented candidate — multi-scale cycles chosen by the inner
            # backtest filter (Phase 3), per horizon. Only added when a cycle survives.
            prod_cycles = select_cycles(logy, doy, rows_per_year=rpy, horizon=h)
            if prod_cycles:
                gbc = walk_forward_gbm(dates, y, horizon=h, use_cycles=True, exog_features=exog_features)
                candidates["gbm_cyc"] = gbc.model_mape
                builders["gbm_cyc"] = lambda hh=h, pp=tuple(prod_cycles): GBMForecaster(
                    horizon=hh, cycle_periods=pp
                ).fit(logy, doy, exog_features=exog_features)

        # Phase 8B: OU / damped mean-reversion candidate (univariate — no exog). It is
        # just one more entry in the pool; ``select_candidate`` (the unchanged naive +
        # margin rule) still decides whether it is ever chosen. Independent of xgboost,
        # so it is available even when gbm is not.
        if enable_ou:
            ou = walk_forward_ou(dates, y, horizon=h)
            candidates["ou"] = ou.model_mape
            builders["ou"] = lambda hh=h: OUForecaster(horizon=hh).fit(logy, doy)

        # Naive benchmark + margin rule (unchanged) decide the winner from the pool.
        model_used, chosen_mape = select_candidate(candidates, naive_mape)
        if model_used != "naive":
            model = builders[model_used]()
            point, lower, upper = model.forecast_interval(
                logy, doy, anchor_idx, y_anchor, h, exog_features=exog_features
            )
        else:
            point, lower, upper = _naive_interval(y_anchor, ret_sigma, h)

        horizon_out[str(h)] = {
            "model_used": model_used,
            "points": [
                {
                    "date": d.isoformat(),
                    "value": round(float(pt), 4),
                    "lower": round(float(lo), 4),
                    "upper": round(float(hi), 4),
                }
                for d, pt, lo, hi in zip(future_dates, point, lower, upper, strict=True)
            ],
            "backtest": {
                "folds": ar.folds,
                "mape_pct": round(chosen_mape, 2) if np.isfinite(chosen_mape) else None,
                "naive_mape_pct": round(naive_mape, 2) if np.isfinite(naive_mape) else None,
                "beats_naive": model_used != "naive",
                "candidates": {k: round(v, 2) for k, v in candidates.items() if np.isfinite(v)},
                "ou_considered": bool(enable_ou),
            },
        }

    return {
        **base,
        "available": True,
        "history_points": len(values),
        "last_date": dates[-1].isoformat(),
        "last_price": round(values[-1], 4),
        "horizons": horizon_out,
    }
