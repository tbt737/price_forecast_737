"""Shared fixtures for ETL integration tests: an in-memory DB with seeded dims."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.models import CommodityGroup, DimCommodity, DimDataSource, DimMarketInstrument, DimRegion
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.seeds.seed_data_sources import seed_data_sources


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
