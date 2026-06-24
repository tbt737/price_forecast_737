"""Integration: build the full schema on SQLite and load all real profiles end-to-end."""

from __future__ import annotations

from app.db.base import Base
from app.models import (  # noqa: F401  (register tables)
    CommodityProfileRegistry,
    CommodityRegionMap,
    DimCommodity,
    DimMarketInstrument,
)
from app.services.profile_loader import load_profiles
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

EXPECTED_TABLES = {
    "dim_commodity",
    "dim_market_instrument",
    "dim_region",
    "commodity_region_map",
    "dim_data_source",
    "fact_price_daily",
    "fact_weather_daily",
    "fact_macro_daily",
    "fact_logistics_periodic",
    "fact_supply_demand_periodic",
    "fact_event_risk",
    "commodity_profile_registry",
}


def _engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )


def test_metadata_has_all_contract_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_create_all_and_load_all_profiles() -> None:
    eng = _engine()
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, future=True)() as session:
        summary = load_profiles(session)
        session.commit()
        assert summary["profile:loaded"] == 16
        assert session.scalar(select(func.count()).select_from(DimCommodity)) == 16
        assert session.scalar(select(func.count()).select_from(CommodityProfileRegistry)) == 16
        assert session.scalar(select(func.count()).select_from(CommodityRegionMap)) > 0
        # 52 baseline + 3 IN_NATIONAL_MEDIAN (onion/chilli/garlic 23y national series)
        assert session.scalar(select(func.count()).select_from(DimMarketInstrument)) == 55
    eng.dispose()
