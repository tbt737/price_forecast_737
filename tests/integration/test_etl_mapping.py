"""Integration: dry-run mapping validates + maps, and writes NO fact rows."""

from __future__ import annotations

from datetime import date

from app.db.base import Base
from app.models import (  # noqa: F401  (register tables)
    FactEventRisk,
    FactLogisticsPeriodic,
    FactMacroDaily,
    FactPriceDaily,
    FactSupplyDemandPeriodic,
    FactWeatherDaily,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from etl.contracts import FactFamily, NormalizedRecord
from etl.mapping import dry_run, map_record
from etl.sources.base import BaseSource
from etl.sources.events import EventRiskSource
from etl.sources.logistics import LogisticsSource
from etl.sources.macro import MacroSource
from etl.sources.market import MarketSource
from etl.sources.supply_demand import SupplyDemandSource
from etl.sources.weather import WeatherSource

FACT_MODELS = (
    FactPriceDaily,
    FactWeatherDaily,
    FactMacroDaily,
    FactLogisticsPeriodic,
    FactSupplyDemandPeriodic,
    FactEventRisk,
)


def _valid_logistics() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.logistics_periodic,
        data_source_code="manual",
        release_date=date(2025, 2, 10),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        indicator_code="BDI",
        value=1500,
    )


def _valid_macro() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.macro_daily,
        data_source_code="manual",
        release_date=date(2025, 1, 10),
        observation_date=date(2025, 1, 10),
        indicator_code="dxy",
        value=104.2,
    )


def test_dry_run_inserts_nothing_property() -> None:
    report = dry_run([_valid_logistics(), _valid_macro()])
    assert report.total == 2
    assert report.valid == 2
    assert report.inserted == 0  # dry-run never writes


def test_mapping_targets_correct_fact_tables() -> None:
    assert map_record(_valid_logistics()).target_table == "fact_logistics_periodic"
    assert map_record(_valid_macro()).target_table == "fact_macro_daily"


def test_valid_mapping_builds_payload() -> None:
    res = map_record(_valid_logistics())
    assert res.ok and res.payload is not None
    assert res.payload["data_source_code"] == "manual"
    assert res.payload["period_start"] == date(2025, 1, 1)
    assert res.payload["period_end"] == date(2025, 1, 31)
    assert res.payload["release_date"] == date(2025, 2, 10)
    assert res.payload["indicator_code"] == "BDI"


def test_invalid_record_not_mapped() -> None:
    bad = NormalizedRecord(**{**_valid_logistics().__dict__, "data_source_code": None, "period_end": date(2024, 1, 1)})
    res = map_record(bad)
    assert not res.ok and res.payload is None
    assert {"MISSING_SOURCE", "INVALID_PERIOD_RANGE"} <= {c.value for c in res.validation.error_codes}


def test_dry_run_against_db_writes_no_facts() -> None:
    """Even with a live DB session available, dry-run must not insert facts."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as session:
        report = dry_run([_valid_logistics(), _valid_macro(), _valid_logistics()])
        session.commit()
        assert report.valid == 3 and report.inserted == 0
        for model in FACT_MODELS:
            count = session.scalar(select(func.count()).select_from(model))
            assert count == 0, f"{model.__tablename__} must have 0 rows after dry-run, got {count}"
    engine.dispose()


def test_stub_sources_are_dry_and_empty() -> None:
    sources: list[BaseSource] = [
        MarketSource(),
        WeatherSource(),
        MacroSource(),
        LogisticsSource(),
        SupplyDemandSource(),
        EventRiskSource(),
    ]
    expected = {
        FactFamily.price_daily,
        FactFamily.weather_daily,
        FactFamily.macro_daily,
        FactFamily.logistics_periodic,
        FactFamily.supply_demand_periodic,
        FactFamily.event_risk,
    }
    assert {s.family for s in sources} == expected
    for src in sources:
        report = src.dry_run()
        assert report.total == 0 and report.inserted == 0
