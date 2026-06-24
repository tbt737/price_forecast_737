"""Read-only endpoints over the commodity dimensions and profile registry.

Phase 2 scope: reads only. No write/ingest/forecast routes yet (deferred to
their phases). Fully generic — nothing is special-cased per commodity.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

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

router = APIRouter(tags=["commodities"])

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
    commodity_code: str, days: int = 365, db: Session = Depends(get_db)
) -> PriceSeriesOut:
    """Daily close series for the commodity's benchmark instrument (the one with the
    most price history), over the last ``days`` days. Empty if no prices ingested."""
    commodity = db.execute(
        select(DimCommodity).filter_by(commodity_code=commodity_code.upper())
    ).scalar_one_or_none()
    if commodity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown commodity '{commodity_code}'")

    best = db.execute(
        select(FactPriceDaily.market_instrument_key)
        .where(FactPriceDaily.commodity_key == commodity.commodity_key)
        .group_by(FactPriceDaily.market_instrument_key)
        .order_by(func.count().desc())
        .limit(1)
    ).scalar_one_or_none()
    if best is None:  # no prices ingested for this commodity yet
        return PriceSeriesOut(commodity_code=commodity.commodity_code, points=[])

    instrument = db.get(DimMarketInstrument, best)
    cutoff = date.today() - timedelta(days=max(1, days))
    rows = db.execute(
        select(FactPriceDaily.price_date, FactPriceDaily.value, FactPriceDaily.currency)
        .where(
            FactPriceDaily.commodity_key == commodity.commodity_key,
            FactPriceDaily.market_instrument_key == best,
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


@router.get("/profiles/{commodity_code}", response_model=ProfileDetailOut)
def get_profile(commodity_code: str, db: Session = Depends(get_db)) -> CommodityProfileRegistry:
    reg = db.execute(
        select(CommodityProfileRegistry).filter_by(commodity_code=commodity_code.upper())
    ).scalar_one_or_none()
    if reg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No profile registered for '{commodity_code}'")
    return reg
