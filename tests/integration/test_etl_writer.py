"""Integration: transaction-safe ETL write path (dry-run/write/idempotent/conflict)."""

from __future__ import annotations

from datetime import date

from app.models import FactPriceDaily, FactSupplyDemandPeriodic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.planner import InsertPlanner
from etl.writer import canonical_identity, write_batch


def _sd(**ov) -> NormalizedRecord:
    base = dict(
        family=FactFamily.supply_demand_periodic, data_source_code="manual", commodity_code="ALPHA",
        metric_code="ending_stocks", period_start=date(2025, 1, 1), period_end=date(2025, 1, 31),
        release_date=date(2025, 2, 10), value=100,
    )
    return NormalizedRecord(**{**base, **ov})


def _price(**ov) -> NormalizedRecord:
    base = dict(
        family=FactFamily.price_daily, data_source_code="manual", commodity_code="ALPHA",
        instrument_code="INST1", observation_date=date(2025, 1, 10), release_date=date(2025, 1, 10),
        value=100, currency="USD",
    )
    return NormalizedRecord(**{**base, **ov})


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# ── dry-run vs write ──────────────────────────────────────────────────────────
def test_dry_run_writes_nothing(seeded_session: Session) -> None:
    report = write_batch(seeded_session, [_sd()], dry_run=True)
    assert report.mode == "dry_run" and report.committed is None and report.inserted == 0
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 0


def test_write_inserts_valid_record(seeded_session: Session) -> None:
    report = write_batch(seeded_session, [_sd()], dry_run=False)
    assert report.committed is True and report.inserted == 1 and report.mode == "write"
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1


# ── idempotency ───────────────────────────────────────────────────────────────
def test_replay_same_record_is_idempotent_no_op(seeded_session: Session) -> None:
    write_batch(seeded_session, [_sd()], dry_run=False)
    report = write_batch(seeded_session, [_sd()], dry_run=False)  # exact replay
    assert report.idempotent == 1 and report.inserted == 0 and report.committed is True
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1  # no duplicate


def test_daily_replay_is_idempotent(seeded_session: Session) -> None:
    write_batch(seeded_session, [_price()], dry_run=False)
    report = write_batch(seeded_session, [_price()], dry_run=False)
    assert report.idempotent == 1 and report.inserted == 0
    assert _count(seeded_session, FactPriceDaily) == 1


# ── conflict ──────────────────────────────────────────────────────────────────
def test_same_grain_different_value_conflicts_no_write(seeded_session: Session) -> None:
    write_batch(seeded_session, [_sd(value=100)], dry_run=False)
    report = write_batch(seeded_session, [_sd(value=200)], dry_run=False)  # same grain, new value
    assert report.conflict == 1 and report.inserted == 0 and report.committed is False
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1
    row = seeded_session.execute(select(FactSupplyDemandPeriodic)).scalar_one()
    assert float(row.value) == 100.0  # original value untouched


# ── atomic rollback ───────────────────────────────────────────────────────────
def test_batch_with_conflict_rolls_back_entirely(seeded_session: Session) -> None:
    write_batch(seeded_session, [_sd(value=100)], dry_run=False)  # pre-existing Jan row
    a_new = _sd(period_start=date(2025, 2, 1), period_end=date(2025, 2, 28), value=50)  # distinct grain
    b_conflict = _sd(value=999)  # same grain as pre-existing, different value
    report = write_batch(seeded_session, [a_new, b_conflict], dry_run=False)

    assert report.committed is False and report.conflict == 1 and report.inserted == 0
    # the new record A must NOT have persisted (whole batch rolled back)
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1
    feb = seeded_session.execute(
        select(FactSupplyDemandPeriodic).where(FactSupplyDemandPeriodic.period_start == date(2025, 2, 1))
    ).scalar_one_or_none()
    assert feb is None


# ── fail-closed lineage ───────────────────────────────────────────────────────
def test_missing_source_rejected_no_write(seeded_session: Session) -> None:
    report = write_batch(seeded_session, [_sd(data_source_code=None)], dry_run=False)
    assert report.rejected == 1 and report.inserted == 0 and report.committed is False
    assert "MISSING_SOURCE" in report.items[0]["error_codes"]
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 0


def test_unknown_source_rejected_no_write(seeded_session: Session) -> None:
    report = write_batch(seeded_session, [_sd(data_source_code="ghost_source")], dry_run=False)
    assert report.rejected == 1 and report.committed is False
    assert "UNKNOWN_SOURCE" in report.items[0]["error_codes"]
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 0


# ── canonical identity ────────────────────────────────────────────────────────
def test_canonical_identity_is_value_independent_and_deterministic(seeded_session: Session) -> None:
    planner = InsertPlanner(seeded_session)
    id_a = canonical_identity(planner.plan(_sd(value=100)))
    id_b = canonical_identity(planner.plan(_sd(value=999)))  # same grain, different value
    id_c = canonical_identity(planner.plan(_sd(metric_code="production_estimate")))  # different grain
    assert id_a == id_b  # value not part of identity
    assert id_a != id_c  # grain field is
