"""Read-only endpoints over the commodity dimensions and profile registry.

Phase 2 scope: reads only. No write/ingest/forecast routes yet (deferred to
their phases). Fully generic — nothing is special-cased per commodity.
"""

from __future__ import annotations

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


@router.get("/profiles/{commodity_code}", response_model=ProfileDetailOut)
def get_profile(commodity_code: str, db: Session = Depends(get_db)) -> CommodityProfileRegistry:
    reg = db.execute(
        select(CommodityProfileRegistry).filter_by(commodity_code=commodity_code.upper())
    ).scalar_one_or_none()
    if reg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No profile registered for '{commodity_code}'")
    return reg
