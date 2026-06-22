"""Integration: the insert planner resolves keys, builds payloads, and never persists."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.planner import InsertPlanner
from etl.validation import ErrorCode


def _price() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.price_daily, data_source_code="manual", release_date=date(2025, 1, 10),
        commodity_code="ALPHA", instrument_code="INST1", observation_date=date(2025, 1, 10),
        currency="USD", attributes={"close": 100.5, "open": 99.0},
    )


def _logistics() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.logistics_periodic, data_source_code="manual", release_date=date(2025, 2, 10),
        region_code="REG1", indicator_code="BDI", period_start=date(2025, 1, 1), period_end=date(2025, 1, 31),
        value=1500,
    )


def _supply_demand() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.supply_demand_periodic, data_source_code="manual", release_date=date(2025, 2, 10),
        commodity_code="ALPHA", metric_code="ending_stocks", period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31), value=100,
    )


def _event() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.event_risk, data_source_code="manual", release_date=date(2025, 6, 2),
        commodity_code="ALPHA", metric_code="el_nino_la_nina", observation_date=date(2025, 6, 1),
    )


def test_plan_targets_correct_tables(seeded_session: Session) -> None:
    planner = InsertPlanner(seeded_session)
    assert planner.plan(_price()).target_table == "fact_price_daily"
    assert planner.plan(_logistics()).target_table == "fact_logistics_periodic"
    assert planner.plan(_supply_demand()).target_table == "fact_supply_demand_periodic"
    assert planner.plan(_event()).target_table == "fact_event_risk"


def test_price_plan_resolves_instrument_key(seeded_session: Session, source_key) -> None:
    plan = InsertPlanner(seeded_session).plan(_price())
    assert plan.would_insert and plan.payload is not None
    assert plan.payload["market_instrument_key"] is not None
    assert plan.payload["commodity_key"] is not None
    assert plan.payload["data_source_key"] == source_key("manual")
    assert plan.payload["price_date"] == date(2025, 1, 10)
    assert plan.payload["close"] == 100.5


def test_periodic_plan_includes_period_and_source(seeded_session: Session) -> None:
    for rec in (_logistics(), _supply_demand()):
        plan = InsertPlanner(seeded_session).plan(rec)
        assert plan.would_insert, plan.error_codes
        assert plan.payload is not None
        for key in ("period_start", "period_end", "release_date", "data_source_key"):
            assert plan.payload.get(key) is not None, f"{rec.family}: missing {key}"
        # the periodic unique grain carries data_source_key + release_date
        assert "data_source_key" in plan.grain_fields
        assert "release_date" in plan.grain_fields


def test_plan_refuses_missing_source(seeded_session: Session) -> None:
    rec = NormalizedRecord(**{**_supply_demand().__dict__, "data_source_code": None})
    plan = InsertPlanner(seeded_session).plan(rec)
    assert not plan.would_insert and plan.payload is None
    assert ErrorCode.MISSING_SOURCE.value in plan.error_codes


def test_plan_refuses_unknown_source(seeded_session: Session) -> None:
    rec = NormalizedRecord(**{**_supply_demand().__dict__, "data_source_code": "nope_source"})
    plan = InsertPlanner(seeded_session).plan(rec)
    assert not plan.would_insert and plan.payload is None
    assert ErrorCode.UNKNOWN_SOURCE.value in plan.error_codes
