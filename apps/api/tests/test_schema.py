"""Schema tests: approved contract tables exist, keys behave, facts are point-in-time safe."""

from __future__ import annotations

from datetime import date

import pytest
from app.db.base import Base
from app.models import (
    CommodityGroup,
    CommodityRegionMap,
    DimCommodity,
    DimDataSource,
    DimMarketInstrument,
    DimRegion,
    FactEventRisk,
    FactMacroDaily,
    FactPriceDaily,
    FactSupplyDemandPeriodic,
    RegionRole,
)
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


def test_contract_tables_exist(engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES.issubset(tables), EXPECTED_TABLES - tables


def test_metadata_matches_expected_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_release_date_indexes_exist(engine) -> None:
    insp = inspect(engine)
    for table in (
        "fact_price_daily",
        "fact_weather_daily",
        "fact_macro_daily",
        "fact_logistics_periodic",
        "fact_supply_demand_periodic",
        "fact_event_risk",
    ):
        names = {ix["name"] for ix in insp.get_indexes(table)}
        assert any(n and n.endswith("release_date") for n in names), (table, names)


def _commodity(session: Session, code: str = "TESTNUT") -> DimCommodity:
    c = DimCommodity(
        commodity_code=code,
        commodity_name="Test",
        commodity_group=CommodityGroup.agriculture,
        base_unit="tonne",
        default_currency="USD",
    )
    session.add(c)
    session.flush()
    return c


def test_commodity_code_unique(session: Session) -> None:
    _commodity(session)
    session.add(
        DimCommodity(
            commodity_code="TESTNUT",
            commodity_name="Other",
            commodity_group=CommodityGroup.energy,
            base_unit="bbl",
            default_currency="USD",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_instrument_code_unique_per_commodity_not_global(session: Session) -> None:
    a = _commodity(session, "AAA")
    b = _commodity(session, "BBB")
    session.add(DimMarketInstrument(commodity_key=a.commodity_key, instrument_code="CN_FOB_QINGDAO"))
    session.add(DimMarketInstrument(commodity_key=b.commodity_key, instrument_code="CN_FOB_QINGDAO"))
    session.flush()  # allowed across commodities

    session.add(DimMarketInstrument(commodity_key=a.commodity_key, instrument_code="CN_FOB_QINGDAO"))
    with pytest.raises(IntegrityError):
        session.flush()  # duplicate within a commodity rejected


def test_commodity_region_map_allows_multiple_roles(session: Session) -> None:
    c = _commodity(session, "MAPNUT")
    r = DimRegion(region_code="CN", region_name="China")
    session.add(r)
    session.flush()
    session.add(CommodityRegionMap(commodity_key=c.commodity_key, region_key=r.region_key, role=RegionRole.production))
    session.add(CommodityRegionMap(commodity_key=c.commodity_key, region_key=r.region_key, role=RegionRole.consumption))
    session.flush()  # same region, two roles -> allowed

    session.add(CommodityRegionMap(commodity_key=c.commodity_key, region_key=r.region_key, role=RegionRole.production))
    with pytest.raises(IntegrityError):
        session.flush()  # duplicate (commodity, region, role) rejected


def test_price_release_date_guard(session: Session) -> None:
    c = _commodity(session, "PNUT")
    session.add(
        FactPriceDaily(
            commodity_key=c.commodity_key,
            price_date=date(2025, 1, 10),
            release_date=date(2025, 1, 1),  # before obs date -> must fail
            close=100,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_price_grain_dedupes_null_instrument(session: Session) -> None:
    c = _commodity(session, "GRN")
    common = dict(commodity_key=c.commodity_key, price_date=date(2025, 1, 10), release_date=date(2025, 1, 10))
    session.add(FactPriceDaily(**common, market_instrument_key=None, revision=0, close=1))
    session.flush()
    session.add(FactPriceDaily(**common, market_instrument_key=None, revision=0, close=2))
    with pytest.raises(IntegrityError):
        session.flush()


def test_macro_grain_dedupes_null_commodity(session: Session) -> None:
    common = dict(macro_date=date(2025, 1, 10), release_date=date(2025, 1, 10), indicator_code="dxy")
    session.add(FactMacroDaily(**common, commodity_key=None, revision=0, value=100))
    session.flush()
    session.add(FactMacroDaily(**common, commodity_key=None, revision=0, value=101))
    with pytest.raises(IntegrityError):
        session.flush()


def _data_source(session: Session, code: str) -> DimDataSource:
    src = DimDataSource(source_code=code, name=f"src {code}")
    session.add(src)
    session.flush()
    return src


def test_periodic_fact_period_end_before_start_rejected(session: Session) -> None:
    c = _commodity(session, "SDP")
    session.add(
        FactSupplyDemandPeriodic(
            commodity_key=c.commodity_key,
            data_source_key=_data_source(session, "SDP_S").data_source_key,
            period_start=date(2025, 2, 1),
            period_end=date(2025, 1, 1),  # end before start -> CHECK fails
            release_date=date(2025, 3, 1),
            metric_code="ending_stocks",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_periodic_fact_release_before_period_end_rejected(session: Session) -> None:
    c = _commodity(session, "SDR")
    session.add(
        FactSupplyDemandPeriodic(
            commodity_key=c.commodity_key,
            data_source_key=_data_source(session, "SDR_S").data_source_key,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            release_date=date(2025, 1, 15),  # released before period end -> CHECK fails
            metric_code="ending_stocks",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_periodic_fact_valid_range_accepted(session: Session) -> None:
    c = _commodity(session, "SDV")
    row = FactSupplyDemandPeriodic(
        commodity_key=c.commodity_key,
        data_source_key=_data_source(session, "SDV_S").data_source_key,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        release_date=date(2025, 2, 10),
        metric_code="ending_stocks",
        value=123,
    )
    session.add(row)
    session.flush()  # must NOT raise
    assert row.sd_id is not None


def test_periodic_fact_requires_data_source(session: Session) -> None:
    """Periodic facts must carry source lineage — NULL data_source_key is rejected."""
    c = _commodity(session, "SDN")
    session.add(
        FactSupplyDemandPeriodic(
            commodity_key=c.commodity_key,
            data_source_key=None,  # NOT NULL -> rejected
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            release_date=date(2025, 2, 10),
            metric_code="ending_stocks",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_periodic_grain_distinguishes_by_release_date(session: Session) -> None:
    """release_date is part of the as-of identity: same period, later release = new row."""
    c = _commodity(session, "SDREL")
    src = _data_source(session, "SREL")
    base = dict(
        commodity_key=c.commodity_key,
        data_source_key=src.data_source_key,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        metric_code="ending_stocks",
        revision=0,
    )
    session.add(FactSupplyDemandPeriodic(**base, release_date=date(2025, 2, 10), value=1))
    session.flush()
    session.add(FactSupplyDemandPeriodic(**base, release_date=date(2025, 3, 10), value=2))
    session.flush()  # different release_date -> distinct as-of row, must NOT raise


def test_periodic_grain_rejects_full_duplicate(session: Session) -> None:
    c = _commodity(session, "SDDUP")
    src = _data_source(session, "SDUP")
    base = dict(
        commodity_key=c.commodity_key,
        data_source_key=src.data_source_key,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        metric_code="ending_stocks",
        revision=0,
        release_date=date(2025, 2, 10),
    )
    session.add(FactSupplyDemandPeriodic(**base, value=1))
    session.flush()
    session.add(FactSupplyDemandPeriodic(**base, value=2))
    with pytest.raises(IntegrityError):
        session.flush()  # identical full grain -> conflict


def test_event_risk_release_guard_and_grain(session: Session) -> None:
    c = _commodity(session, "EVT")
    # release before event -> fail
    session.add(
        FactEventRisk(
            commodity_key=c.commodity_key,
            event_date=date(2025, 6, 1),
            release_date=date(2025, 5, 1),
            metric_code="el_nino_la_nina",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
