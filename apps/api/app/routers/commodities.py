"""Read-only endpoints over the commodity dimensions and profile registry.

Generic across all commodity/equity profiles. Forecast compute is gated by
SEC-2 (X-Internal-Key) and cached until the price fingerprint changes.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import require_internal_key
from app.db.session import get_db
from app.models import (
    CommodityProfileRegistry,
    DimCommodity,
    DimDataSource,
    DimMarketInstrument,
    DimRegion,
    FactEventRisk,
    FactLogisticsPeriodic,
    FactMacroDaily,
    FactPriceDaily,
    FactSupplyDemandPeriodic,
    FactWeatherDaily,
)
from app.schemas.commodity import (
    CommodityDetailOut,
    CommodityOut,
    PriceSeriesOut,
    ProfileDetailOut,
    ProfileRegistryOut,
    StatsOut,
)
from app.schemas.forecast import ForecastOut

router = APIRouter(tags=["commodities"])
logger = logging.getLogger(__name__)

_FACT_MODELS = (
    FactPriceDaily, FactWeatherDaily, FactMacroDaily,
    FactLogisticsPeriodic, FactSupplyDemandPeriodic, FactEventRisk,
)


def _count(model: type) -> Any:
    """Scalar subquery: COUNT(*) of a table, usable as a SELECT column."""
    return select(func.count()).select_from(model).scalar_subquery()


@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)) -> StatsOut:
    """Read-only summary counts for the dashboard header.

    Single round-trip: all counts are scalar subqueries in one SELECT (was 11
    separate queries — meaningful on a high-latency remote DB).
    """
    fact_labels = [f"fact_{i}" for i in range(len(_FACT_MODELS))]
    row = db.execute(
        select(
            _count(DimCommodity).label("commodities"),
            _count(CommodityProfileRegistry).label("profiles"),
            _count(DimMarketInstrument).label("instruments"),
            _count(DimRegion).label("regions"),
            _count(DimDataSource).label("data_sources"),
            *[_count(model).label(label) for model, label in zip(_FACT_MODELS, fact_labels, strict=True)],
        )
    ).mappings().one()

    return StatsOut(
        commodities=row["commodities"],
        profiles=row["profiles"],
        instruments=row["instruments"],
        regions=row["regions"],
        data_sources=row["data_sources"],
        fact_rows=sum(row[label] for label in fact_labels),
    )


@router.get("/commodities", response_model=list[CommodityOut])
def list_commodities(db: Session = Depends(get_db)) -> list[DimCommodity]:
    return list(db.execute(select(DimCommodity).order_by(DimCommodity.commodity_code)).scalars())


@router.get("/commodities/{commodity_code}", response_model=CommodityDetailOut)
def get_commodity(commodity_code: str, db: Session = Depends(get_db)) -> DimCommodity:
    commodity = db.execute(
        select(DimCommodity)
        .options(selectinload(DimCommodity.instruments))
        .filter_by(commodity_code=commodity_code.upper())
    ).scalar_one_or_none()
    if commodity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown commodity '{commodity_code}'")
    return commodity


@router.get("/profiles", response_model=list[ProfileRegistryOut])
def list_profiles(db: Session = Depends(get_db)) -> list[CommodityProfileRegistry]:
    return list(
        db.execute(
            select(CommodityProfileRegistry).order_by(CommodityProfileRegistry.commodity_code)
        ).scalars()
    )


@router.get("/commodities/{commodity_code}/prices", response_model=PriceSeriesOut)
def get_commodity_prices(
    commodity_code: str,
    days: int = Query(365, ge=1, le=20000, description="lookback window in days (bounded to avoid date overflow)"),
    db: Session = Depends(get_db),
) -> PriceSeriesOut:
    """Daily close series for the commodity's benchmark instrument (the one with the
    most price history), over the last ``days`` days. Empty if no prices ingested.
    ``days`` is bounded to [1, 20000]; out-of-range values return 422 (never a 500 from
    a ``date`` underflow)."""
    commodity = db.execute(
        select(DimCommodity).filter_by(commodity_code=commodity_code.upper())
    ).scalar_one_or_none()
    if commodity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown commodity '{commodity_code}'")

    # Benchmark by DISTINCT dates; serve ONLY the instrument's latest revision — a
    # restated (adjusted) series is re-ingested at revision+1 (etl/restatement.py) and
    # mixing revisions would splice two adjustment bases (see ml.forecast counterpart).
    best = db.execute(
        select(FactPriceDaily.market_instrument_key)
        .where(FactPriceDaily.commodity_key == commodity.commodity_key)
        .group_by(FactPriceDaily.market_instrument_key)
        .order_by(func.count(func.distinct(FactPriceDaily.price_date)).desc())
        .limit(1)
    ).scalar_one_or_none()
    if best is None:  # no prices ingested for this commodity yet
        return PriceSeriesOut(commodity_code=commodity.commodity_code, points=[])

    instrument = db.get(DimMarketInstrument, best)
    latest_revision = (
        select(func.max(FactPriceDaily.revision))
        .where(
            FactPriceDaily.commodity_key == commodity.commodity_key,
            FactPriceDaily.market_instrument_key == best,
        )
        .scalar_subquery()
    )
    cutoff = date.today() - timedelta(days=max(1, days))
    rows = db.execute(
        select(FactPriceDaily.price_date, FactPriceDaily.value, FactPriceDaily.currency)
        .where(
            FactPriceDaily.commodity_key == commodity.commodity_key,
            FactPriceDaily.market_instrument_key == best,
            FactPriceDaily.revision == latest_revision,
            FactPriceDaily.price_date >= cutoff,
        )
        .order_by(FactPriceDaily.price_date)
    ).all()

    points = [{"date": r.price_date, "value": float(r.value)} for r in rows if r.value is not None]
    currency = rows[0].currency if rows else (instrument.currency if instrument else None)
    return PriceSeriesOut(
        commodity_code=commodity.commodity_code,
        instrument_code=instrument.instrument_code if instrument else None,
        currency=currency,
        points=points,  # type: ignore[arg-type]
    )


# In-process forecast cache. Forecasting is a multi-second walk-forward; the price
# data only changes on (infrequent) ingest. Cache the result keyed by a cheap data
# fingerprint (row count + latest date + max revision) that auto-invalidates on new
# data or restatement. Within FINGERPRINT_TTL we serve the cached result without even
# re-running the fingerprint query, so warm repeat calls are instant.
_FORECAST_CACHE: dict[str, tuple[float, tuple[int, str | None, int], dict[str, Any]]] = {}
FINGERPRINT_TTL = 300.0  # seconds before re-checking whether the data changed


@router.get(
    "/commodities/{commodity_code}/forecast",
    response_model=ForecastOut,
    dependencies=[Depends(require_internal_key)],  # SEC-2: compute-heavy, gated when key is set
)
def get_commodity_forecast(commodity_code: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Ridge/XGBoost (+cycle) price forecast for 30 & 90 trading days, each with an
    ~80% band and an honest walk-forward backtest (MAPE vs naive). Falls back to a
    flat naive line per-horizon where no model beats naive out-of-sample. Cached per
    commodity until its price data changes. ``available: false`` with too little history."""
    code = commodity_code.upper()
    cached = _FORECAST_CACHE.get(code)
    if cached is not None and time.monotonic() - cached[0] < FINGERPRINT_TTL:
        return cached[2]  # warm: skip even the fingerprint query

    commodity = db.execute(select(DimCommodity).filter_by(commodity_code=code)).scalar_one_or_none()
    if commodity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown commodity '{commodity_code}'")

    row = db.execute(
        select(
            func.count(),
            func.max(FactPriceDaily.price_date),
            func.max(FactPriceDaily.revision),
        ).where(FactPriceDaily.commodity_key == commodity.commodity_key)
    ).one()
    # Fingerprint includes max(revision): a restatement can rewrite values without
    # changing max(price_date) or (on a same-length reload) even the raw row count
    # of the canonical series alone; the extra revision rows always bump this.
    fingerprint = (
        int(row[0]),
        row[1].isoformat() if row[1] else None,
        int(row[2] or 0),
    )
    if cached is not None and cached[1] == fingerprint:
        _FORECAST_CACHE[code] = (time.monotonic(), fingerprint, cached[2])  # data unchanged; refresh TTL
        return cached[2]

    from ml.forecast import forecast_commodity

    try:
        result = forecast_commodity(db, code)
    except Exception:  # noqa: BLE001 — fail closed: never surface internals (traceback, module path, DB URL)
        logger.exception("forecast computation failed for %s", code)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Forecast service temporarily unavailable"
        ) from None
    _FORECAST_CACHE[code] = (time.monotonic(), fingerprint, result)
    return result


@router.get("/profiles/{commodity_code}", response_model=ProfileDetailOut)
def get_profile(commodity_code: str, db: Session = Depends(get_db)) -> CommodityProfileRegistry:
    reg = db.execute(
        select(CommodityProfileRegistry).filter_by(commodity_code=commodity_code.upper())
    ).scalar_one_or_none()
    if reg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No profile registered for '{commodity_code}'")
    return reg
