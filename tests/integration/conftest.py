"""Shared fixtures for ETL integration tests: an in-memory DB with seeded dims."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.models import CommodityGroup, DimCommodity, DimDataSource, DimMarketInstrument, DimRegion
from app.services.profile_loader import load_profiles
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.seeds.seed_data_sources import seed_data_sources


def _memory_engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )


@pytest.fixture()
def seeded_session() -> Iterator[Session]:
    """Session with seeded data sources + one generic commodity/region/instrument.

    Generic codes (ALPHA / REG1 / INST1) — no real commodity is special-cased.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()

    seed_data_sources(session)
    commodity = DimCommodity(
        commodity_code="ALPHA",
        commodity_name="Alpha",
        commodity_group=CommodityGroup.agriculture,
        base_unit="tonne",
        default_currency="USD",
    )
    session.add(commodity)
    session.flush()
    session.add(DimRegion(region_code="REG1", region_name="Region One"))
    session.add(DimMarketInstrument(commodity_key=commodity.commodity_key, instrument_code="INST1", exchange="X"))
    session.commit()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def source_key(seeded_session: Session):
    """Factory: source_code -> data_source_key for the seeded session."""

    def _get(code: str) -> int:
        return seeded_session.execute(
            select(DimDataSource.data_source_key).filter_by(source_code=code)
        ).scalar_one()

    return _get


@pytest.fixture()
def profiles_session() -> Iterator[Session]:
    """Session with seeded sources + all real commodity profiles loaded.

    Gives real dimension codes (ROBUSTA/GOLD/RICE, ICE_RC, VN_TAY_NGUYEN, ...) so
    fixture records resolve. No fact rows are inserted.
    """
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    seed_data_sources(session)
    load_profiles(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
