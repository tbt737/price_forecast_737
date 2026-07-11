"""Loader tests: dedupe rules, region-map roles, idempotency, checksum, real profiles."""

from __future__ import annotations

from app.models import (
    CommodityProfileRegistry,
    CommodityRegionMap,
    DimCommodity,
    DimDataSource,
    DimMarketInstrument,
    DimRegion,
)
from app.services.profile_loader import LoadSummary, load_profile, load_profiles
from sqlalchemy import select
from sqlalchemy.orm import Session

PROFILE_A = {
    "commodity_code": "ALPHA",
    "commodity_name": "Alpha",
    "commodity_group": "agriculture",
    "base_unit": "tonne",
    "default_currency": "USD",
    "market_instruments": [{"instrument_code": "CN_FOB_QINGDAO", "exchange": "X"}],
    "production_regions": [{"region_code": "CN", "name": "China"}],
    "consumption_regions": [{"region_code": "CN", "name": "China (domestic)"}],
    "data_sources": [{"source_code": "TRIDGE", "name": "Tridge"}],
}
PROFILE_B = {
    "commodity_code": "BETA",
    "commodity_name": "Beta",
    "commodity_group": "metal",
    "base_unit": "tonne",
    "default_currency": "USD",
    "market_instruments": [{"instrument_code": "CN_FOB_QINGDAO", "exchange": "Y"}],
    "production_regions": [{"region_code": "CN", "name": "China (smelting)"}],
    "data_sources": [{"source_code": "TRIDGE", "name": "Tridge"}],
}


def _count(session: Session, model) -> int:
    return len(session.execute(select(model)).scalars().all())


def test_shared_dims_dedupe_instruments_per_commodity(session: Session) -> None:
    s = LoadSummary()
    load_profile(session, PROFILE_A, s)
    load_profile(session, PROFILE_B, s)
    session.flush()

    assert _count(session, DimRegion) == 1  # CN deduped globally
    assert _count(session, DimDataSource) == 1  # TRIDGE deduped
    assert _count(session, DimMarketInstrument) == 2  # per-commodity
    # CN mapped to ALPHA(production+consumption) + BETA(production) = 3 role links
    assert _count(session, CommodityRegionMap) == 3
    region = session.execute(select(DimRegion).filter_by(region_code="CN")).scalar_one()
    assert region.region_name == "China"  # canonical first-seen


def test_idempotent_and_checksum_unchanged(session: Session) -> None:
    s1 = LoadSummary()
    load_profile(session, PROFILE_A, s1, raw_text="A")
    session.flush()
    before = (
        _count(session, DimCommodity),
        _count(session, CommodityProfileRegistry),
        _count(session, CommodityRegionMap),
    )

    s2 = LoadSummary()
    load_profile(session, PROFILE_A, s2, raw_text="A")  # same content
    session.flush()
    after = (
        _count(session, DimCommodity),
        _count(session, CommodityProfileRegistry),
        _count(session, CommodityRegionMap),
    )

    assert before == after
    assert s2["registry:unchanged"] == 1
    assert s2["dim_commodity:created"] == 0
    assert s2["commodity_region_map:created"] == 0


def test_changed_profile_bumps_version(session: Session) -> None:
    s = LoadSummary()
    load_profile(session, PROFILE_A, s, raw_text="v1")
    session.flush()
    load_profile(session, PROFILE_A, s, raw_text="v2-different")  # checksum changes
    session.flush()
    reg = session.execute(select(CommodityProfileRegistry).filter_by(commodity_code="ALPHA")).scalar_one()
    assert reg.version == 2


def test_loads_all_real_profiles(session: Session) -> None:
    summary = load_profiles(session)
    session.commit()

    assert summary["profile:loaded"] == 51  # 21 commodities + 30 VN30 equities
    assert _count(session, DimCommodity) == 51
    assert _count(session, CommodityProfileRegistry) == 51
    assert _count(session, CommodityRegionMap) > 0

    groups = {g for (g,) in session.execute(select(DimCommodity.commodity_group).distinct())}
    assert {"agriculture", "energy", "metal", "logistics", "equity"}.issubset({g.value for g in groups})

    reg = session.execute(select(CommodityProfileRegistry).filter_by(commodity_code="ROBUSTA")).scalar_one()
    assert reg.profile["commodity_group"] == "agriculture"
    assert reg.checksum and len(reg.checksum) == 64
