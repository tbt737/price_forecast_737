"""Integration: conflict pre-check + transactional simulation that leaves no rows."""

from __future__ import annotations

from datetime import date

from app.models import DimCommodity, FactSupplyDemandPeriodic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.planner import InsertPlanner, simulate_and_rollback


def _sd_record() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.supply_demand_periodic, data_source_code="manual", release_date=date(2025, 2, 10),
        commodity_code="ALPHA", metric_code="ending_stocks", period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31), value=100,
    )


def _logistics_record() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.logistics_periodic, data_source_code="manual", release_date=date(2025, 2, 10),
        region_code="REG1", indicator_code="BDI", period_start=date(2025, 1, 1), period_end=date(2025, 1, 31),
        value=1500,
    )


def test_conflict_detects_duplicate_periodic_grain(seeded_session: Session, source_key) -> None:
    commodity_key = seeded_session.execute(
        select(DimCommodity.commodity_key).filter_by(commodity_code="ALPHA")
    ).scalar_one()
    src = source_key("manual")
    # Persist an existing row with the same grain as _sd_record().
    seeded_session.add(
        FactSupplyDemandPeriodic(
            commodity_key=commodity_key, data_source_key=src, metric_code="ending_stocks",
            period_start=date(2025, 1, 1), period_end=date(2025, 1, 31), release_date=date(2025, 2, 10),
            revision=0, value=100,
        )
    )
    seeded_session.commit()

    plan = InsertPlanner(seeded_session).plan(_sd_record())
    assert plan.conflict is True
    assert plan.would_insert is False  # duplicate grain -> must not insert

    # A different release_date is a distinct as-of row -> no conflict.
    fresh = NormalizedRecord(**{**_sd_record().__dict__, "release_date": date(2025, 3, 10)})
    plan2 = InsertPlanner(seeded_session).plan(fresh)
    assert plan2.conflict is False and plan2.would_insert is True


def test_simulation_rolls_back_and_leaves_counts_unchanged(seeded_session: Session) -> None:
    before = seeded_session.scalar(select(func.count()).select_from(FactSupplyDemandPeriodic))

    report = simulate_and_rollback(seeded_session, [_sd_record(), _logistics_record()])

    assert report.inserted_in_savepoint == 2  # both would insert inside the savepoint
    assert report.counts_within != report.counts_before  # rows existed transiently
    assert report.counts_before == report.counts_after  # ...but nothing persisted
    assert report.persisted_change is False

    after = seeded_session.scalar(select(func.count()).select_from(FactSupplyDemandPeriodic))
    assert before == after == 0
