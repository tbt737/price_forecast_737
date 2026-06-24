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

from ml.backtests.walk_forward import walk_forward  # noqa: E402
from ml.models.baseline import FourierTrendForecaster  # noqa: E402

MIN_HISTORY = 252  # ~1 trading year required to fit the seasonal baseline


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


def forecast_commodity(
    session: Session,
    commodity_code: str,
    *,
    horizons: tuple[int, ...] = (30, 90),
    harmonics: int = 3,
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
        "model": "fourier_trend",
        "harmonics": harmonics,
    }
    # drop non-positive prices (e.g. the 2020 negative-oil episode) before log-fitting
    clean = [(d, v) for d, v in zip(dates, values, strict=True) if v > 0]
    dates = [c[0] for c in clean]
    values = [c[1] for c in clean]
    if len(values) < MIN_HISTORY:
        return {**base, "available": False, "reason": f"need >= {MIN_HISTORY} positive prices, have {len(values)}"}

    start = dates[0]
    t = np.array([(d - start).days for d in dates], dtype=float)
    y = np.array(values, dtype=float)
    model = FourierTrendForecaster(harmonics=harmonics).fit(t, y)
    t_anchor = float(t[-1])
    y_anchor = float(values[-1])

    horizon_out: dict[str, Any] = {}
    for h in horizons:
        future_dates = _next_business_days(dates[-1], h)
        t_future = np.array([(d - start).days for d in future_dates], dtype=float)
        point, lower, upper = model.forecast_interval(t_anchor, y_anchor, t_future)
        bt = walk_forward(t, y, horizon=h, harmonics=harmonics)
        horizon_out[str(h)] = {
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
                "folds": bt.folds,
                "mape_pct": round(bt.model_mape, 2),
                "rmse": round(bt.model_rmse, 4),
                "naive_mape_pct": round(bt.naive_mape, 2),
                "beats_naive": bt.beats_naive,
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
