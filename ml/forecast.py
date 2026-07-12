"""Forecast orchestrator helpers + compatibility wrapper for CommodityPricePredictor.

Production forecasting lives in ``ml.predictor.CommodityPricePredictor``.
``forecast_commodity`` remains the public entry point used by the API and
forecast-log writer — it delegates to that class unchanged in payload shape.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

_API_DIR = Path(__file__).resolve().parent.parent / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from app.models import DimCommodity, DimMarketInstrument, FactPriceDaily  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

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
    chosen_mape)`` where ``chosen_mape`` is the backtest MAPE of the model actually used:
    when ``model_used == "naive"`` (the benchmark held) that is ``naive_mape`` itself — not
    the losing candidate's MAPE."""
    finite = {k: v for k, v in candidates.items() if np.isfinite(v)}
    best = min(finite, key=lambda k: finite[k]) if finite else None
    if best is not None and np.isfinite(naive_mape) and finite[best] < naive_mape * (1.0 - margin):
        return best, finite[best]
    return "naive", naive_mape


def impute_exog(df_view: Any, dates: list[date]) -> Any:
    """Causal, point-in-time imputation of the exogenous feature frame.

    ``ffill`` carries the last KNOWN past value forward; the frame is reindexed onto the
    price ``dates`` (still forward-fill). Any remaining NaN are *leading* rows — dates
    before a feature's first observation, where no past value exists — and get a neutral
    ``0.0``. Crucially, **no full-history statistic** (e.g. a global median) is used: every
    imputed value at row ``t`` depends only on data at or before ``t``, so nothing leaks the
    future into an early walk-forward backtest fold (the bug this replaces used
    ``df.median()`` over the whole series)."""
    df = df_view.sort_index().ffill()
    df = df.reindex(dates, method="ffill")
    return df.fillna(0.0)


def load_price_series(session: Session, commodity_code: str) -> dict[str, Any] | None:
    commodity = session.execute(
        select(DimCommodity).filter_by(commodity_code=commodity_code.upper())
    ).scalar_one_or_none()
    if commodity is None:
        return None
    # Most-populated instrument by DISTINCT dates (a restated series carries several
    # revisions of the same dates — raw row counts would bias toward restated series).
    instrument_key = session.execute(
        select(FactPriceDaily.market_instrument_key)
        .where(FactPriceDaily.commodity_key == commodity.commodity_key)
        .group_by(FactPriceDaily.market_instrument_key)
        .order_by(func.count(func.distinct(FactPriceDaily.price_date)).desc())
        .limit(1)
    ).scalar_one_or_none()
    if instrument_key is None:
        return {"commodity": commodity, "instrument": None, "dates": [], "values": []}

    instrument = session.get(DimMarketInstrument, instrument_key)
    # Single-basis rule: an ADJUSTED source restates its whole history at corporate
    # actions and is re-ingested at revision+1 (etl/restatement.py) — mixing revisions
    # would splice two adjustment bases, so read ONLY the instrument's latest revision.
    latest_revision = (
        select(func.max(FactPriceDaily.revision))
        .where(
            FactPriceDaily.commodity_key == commodity.commodity_key,
            FactPriceDaily.market_instrument_key == instrument_key,
        )
        .scalar_subquery()
    )
    rows = session.execute(
        select(FactPriceDaily.price_date, FactPriceDaily.value)
        .where(
            FactPriceDaily.commodity_key == commodity.commodity_key,
            FactPriceDaily.market_instrument_key == instrument_key,
            FactPriceDaily.revision == latest_revision,
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
    l2: float = 5.0,
    enable_ou: bool = OU_ENABLED,
) -> dict[str, Any]:
    """Compatibility wrapper — delegates to ``CommodityPricePredictor`` (deep-research spec)."""
    from ml.predictor import CommodityPricePredictor

    return (
        CommodityPricePredictor(horizons=horizons, l2=l2, enable_ou=enable_ou)
        .fit_from_session(session, commodity_code)
        .forecast()
    )
