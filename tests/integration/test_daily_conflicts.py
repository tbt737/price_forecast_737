"""Integration: daily-fact conflict pre-checks (price/weather/macro/event_risk).

Runs on in-memory SQLite by default. Set ``CQP_TEST_PG_URL`` to also run the
matrix against real PostgreSQL (skipped cleanly otherwise). The manual Docker
PostgreSQL smoke covers the same families regardless.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from app.db.base import Base
from app.models import CommodityGroup, DimCommodity, DimMarketInstrument, DimRegion
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.seeds.seed_data_sources import seed_data_sources
from etl.conflicts import TARGET_MODELS
from etl.contracts import FactFamily, NormalizedRecord
from etl.planner import InsertPlanner

DAILY_FAMILIES = [
    FactFamily.price_daily,
    FactFamily.weather_daily,
    FactFamily.macro_daily,
    FactFamily.event_risk,
]


def _price(**ov) -> NormalizedRecord:
    base = dict(family=FactFamily.price_daily, data_source_code="manual", commodity_code="ALPHA",
                instrument_code="INST1", observation_date=date(2025, 1, 10), release_date=date(2025, 1, 10))
    return NormalizedRecord(**{**base, **ov})


def _weather(**ov) -> NormalizedRecord:
    base = dict(family=FactFamily.weather_daily, data_source_code="manual", commodity_code="ALPHA",
                region_code="REG1", metric_code="rainfall_mm", observation_date=date(2025, 1, 10),
                release_date=date(2025, 1, 11))
    return NormalizedRecord(**{**base, **ov})


def _macro(**ov) -> NormalizedRecord:
    base = dict(family=FactFamily.macro_daily, data_source_code="manual", commodity_code="ALPHA",
                indicator_code="dxy", observation_date=date(2025, 1, 10), release_date=date(2025, 1, 10))
    return NormalizedRecord(**{**base, **ov})


def _event(**ov) -> NormalizedRecord:
    base = dict(family=FactFamily.event_risk, data_source_code="manual", commodity_code="ALPHA",
                region_code="REG1", metric_code="el_nino_la_nina", observation_date=date(2025, 6, 1),
                release_date=date(2025, 6, 2))
    return NormalizedRecord(**{**base, **ov})


FACTORY = {
    FactFamily.price_daily: _price,
    FactFamily.weather_daily: _weather,
    FactFamily.macro_daily: _macro,
    FactFamily.event_risk: _event,
}


def _seed_dims(session: Session) -> None:
    seed_data_sources(session)
    commodity = DimCommodity(commodity_code="ALPHA", commodity_name="Alpha",
                             commodity_group=CommodityGroup.agriculture, base_unit="tonne", default_currency="USD")
    session.add(commodity)
    session.flush()
    session.add(DimRegion(region_code="REG1", region_name="Region One"))
    session.add(DimMarketInstrument(commodity_key=commodity.commodity_key, instrument_code="INST1", exchange="X"))
    session.flush()


def _persist_plan(session: Session, rec: NormalizedRecord) -> None:
    """Plan a record (must be insertable) and durably insert it into the test DB."""
    plan = InsertPlanner(session).plan(rec)
    assert plan.would_insert and plan.conflict is False, plan.error_codes
    session.add(TARGET_MODELS[rec.family](**plan.payload))
    session.commit()


# ── SQLite matrix ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("family", DAILY_FAMILIES, ids=lambda f: f.value)
def test_fresh_record_no_conflict(seeded_session: Session, family: FactFamily) -> None:
    plan = InsertPlanner(seeded_session).plan(FACTORY[family]())
    assert plan.would_insert is True and plan.conflict is False


@pytest.mark.parametrize("family", DAILY_FAMILIES, ids=lambda f: f.value)
def test_duplicate_grain_conflicts(seeded_session: Session, family: FactFamily) -> None:
    rec = FACTORY[family]()
    _persist_plan(seeded_session, rec)
    plan = InsertPlanner(seeded_session).plan(rec)
    assert plan.conflict is True and plan.would_insert is False


@pytest.mark.parametrize("family", DAILY_FAMILIES, ids=lambda f: f.value)
def test_revision_distinguishes(seeded_session: Session, family: FactFamily) -> None:
    _persist_plan(seeded_session, FACTORY[family]())
    plan = InsertPlanner(seeded_session).plan(FACTORY[family](revision=1))
    assert plan.conflict is False and plan.would_insert is True


@pytest.mark.parametrize("family", DAILY_FAMILIES, ids=lambda f: f.value)
def test_different_date_distinguishes(seeded_session: Session, family: FactFamily) -> None:
    _persist_plan(seeded_session, FACTORY[family]())
    later = FACTORY[family](observation_date=date(2025, 7, 7), release_date=date(2025, 7, 8))
    plan = InsertPlanner(seeded_session).plan(later)
    assert plan.conflict is False and plan.would_insert is True


# ── NULL-safe matching for nullable keys ──────────────────────────────────────
def test_macro_null_commodity_is_nullsafe(seeded_session: Session) -> None:
    _persist_plan(seeded_session, _macro(commodity_code=None))  # commodity_key NULL
    # another NULL-commodity row with same grain -> conflict (NULL matches NULL)
    assert InsertPlanner(seeded_session).plan(_macro(commodity_code=None)).conflict is True
    # a non-null commodity differs -> no conflict with the NULL row
    assert InsertPlanner(seeded_session).plan(_macro()).conflict is False


def test_event_null_region_is_nullsafe(seeded_session: Session) -> None:
    _persist_plan(seeded_session, _event(region_code=None))  # region_key NULL
    assert InsertPlanner(seeded_session).plan(_event(region_code=None)).conflict is True
    assert InsertPlanner(seeded_session).plan(_event()).conflict is False


def test_price_null_instrument_is_nullsafe(seeded_session: Session) -> None:
    _persist_plan(seeded_session, _price(instrument_code=None))  # market_instrument_key NULL
    assert InsertPlanner(seeded_session).plan(_price(instrument_code=None)).conflict is True
    assert InsertPlanner(seeded_session).plan(_price()).conflict is False


# ── Env-gated PostgreSQL variant ──────────────────────────────────────────────
@pytest.mark.skipif(not os.getenv("CQP_TEST_PG_URL"), reason="set CQP_TEST_PG_URL to run on PostgreSQL")
def test_daily_conflicts_on_postgres() -> None:
    engine = create_engine(os.environ["CQP_TEST_PG_URL"], future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        _seed_dims(session)
        session.commit()
        for family in DAILY_FAMILIES:
            rec = FACTORY[family]()
            _persist_plan(session, rec)
            plan = InsertPlanner(session).plan(rec)
            assert plan.conflict is True and plan.would_insert is False, family
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
