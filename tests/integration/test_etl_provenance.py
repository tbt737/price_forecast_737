"""Integration: Phase 4B source provenance & replay contract."""

from __future__ import annotations

import hashlib
from datetime import date

from app.models import FactPriceDaily, FactSupplyDemandPeriodic
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.writer import write_batch

HASH_1 = hashlib.sha256(b"payload-v1").hexdigest()
HASH_2 = hashlib.sha256(b"payload-v2").hexdigest()


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


# ── schema ────────────────────────────────────────────────────────────────────
def test_provenance_columns_exist_and_nullable(seeded_session: Session) -> None:
    cols = {c["name"]: c for c in inspect(seeded_session.get_bind()).get_columns("fact_supply_demand_periodic")}
    assert "source_record_id" in cols and cols["source_record_id"]["nullable"] is True
    assert "source_payload_hash" in cols and cols["source_payload_hash"]["nullable"] is True
    # grain columns untouched (no provenance added to the unique grain)
    model_cols = {c.name for c in FactSupplyDemandPeriodic.__table__.columns}
    assert {"source_record_id", "source_payload_hash"} <= model_cols


# ── backward compatibility (Phase 4A behaviour for no-provenance records) ──────
def test_record_without_provenance_still_inserts(seeded_session: Session) -> None:
    report = write_batch(seeded_session, [_sd()], dry_run=False)
    assert report.committed is True and report.inserted == 1
    row = seeded_session.execute(select(FactSupplyDemandPeriodic)).scalar_one()
    assert row.source_record_id is None and row.source_payload_hash is None


# ── provenance persistence ────────────────────────────────────────────────────
def test_provenance_fields_are_persisted(seeded_session: Session) -> None:
    write_batch(seeded_session, [_sd(source_record_id="SRC-1", source_payload_hash=HASH_1)], dry_run=False)
    row = seeded_session.execute(select(FactSupplyDemandPeriodic)).scalar_one()
    assert row.source_record_id == "SRC-1" and row.source_payload_hash == HASH_1


def test_dry_run_with_provenance_writes_nothing(seeded_session: Session) -> None:
    report = write_batch(
        seeded_session, [_sd(source_record_id="SRC-1", source_payload_hash=HASH_1)], dry_run=True
    )
    assert report.committed is None and report.inserted == 0
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 0


# ── provenance replay / idempotency ───────────────────────────────────────────
def test_replay_same_provenance_same_value_is_idempotent(seeded_session: Session) -> None:
    rec = _sd(source_record_id="SRC-1", source_payload_hash=HASH_1)
    write_batch(seeded_session, [rec], dry_run=False)
    report = write_batch(seeded_session, [rec], dry_run=False)  # exact replay
    assert report.idempotent == 1 and report.inserted == 0 and report.committed is True
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1  # no duplicate


def test_same_provenance_changed_hash_is_conflict(seeded_session: Session) -> None:
    write_batch(seeded_session, [_sd(source_record_id="SRC-1", source_payload_hash=HASH_1)], dry_run=False)
    report = write_batch(
        seeded_session, [_sd(source_record_id="SRC-1", source_payload_hash=HASH_2)], dry_run=False
    )
    assert report.conflict == 1 and report.inserted == 0 and report.committed is False
    assert report.items[0].get("conflict_kind") == "provenance"
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1


def test_same_provenance_changed_value_is_conflict(seeded_session: Session) -> None:
    write_batch(seeded_session, [_sd(source_record_id="SRC-1", source_payload_hash=HASH_1, value=100)], dry_run=False)
    report = write_batch(
        seeded_session, [_sd(source_record_id="SRC-1", source_payload_hash=HASH_1, value=200)], dry_run=False
    )
    assert report.conflict == 1 and report.committed is False
    assert report.items[0].get("conflict_kind") == "provenance"
    row = seeded_session.execute(select(FactSupplyDemandPeriodic)).scalar_one()
    assert float(row.value) == 100.0  # original untouched


# ── provenance must NOT bypass grain conflict ─────────────────────────────────
def test_same_grain_different_provenance_keeps_grain_conflict(seeded_session: Session) -> None:
    write_batch(seeded_session, [_sd(source_record_id="SRC-A", source_payload_hash=HASH_1, value=100)], dry_run=False)
    # different provenance (SRC-B) but SAME grain and a different value -> grain conflict
    report = write_batch(
        seeded_session, [_sd(source_record_id="SRC-B", source_payload_hash=HASH_2, value=200)], dry_run=False
    )
    assert report.conflict == 1 and report.inserted == 0 and report.committed is False
    assert report.items[0].get("conflict_kind") == "grain"
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1


# ── atomic rollback with a provenance conflict ────────────────────────────────
def test_atomic_rollback_on_provenance_conflict(seeded_session: Session) -> None:
    write_batch(seeded_session, [_sd(source_record_id="SRC-X", source_payload_hash=HASH_1, value=100)], dry_run=False)
    a_new = _sd(period_start=date(2025, 2, 1), period_end=date(2025, 2, 28),
                source_record_id="SRC-NEW", source_payload_hash=HASH_2, value=50)  # distinct grain + provenance
    b_conflict = _sd(source_record_id="SRC-X", source_payload_hash=HASH_2, value=999)  # provenance conflict
    report = write_batch(seeded_session, [a_new, b_conflict], dry_run=False)

    assert report.committed is False and report.conflict == 1 and report.inserted == 0
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1  # A rolled back too
    feb = seeded_session.execute(
        select(FactSupplyDemandPeriodic).where(FactSupplyDemandPeriodic.period_start == date(2025, 2, 1))
    ).scalar_one_or_none()
    assert feb is None


# ── daily facts: provenance keys on data_source_key, which is NOT in the daily grain ──
def test_daily_provenance_persists_and_replays_idempotent(seeded_session: Session) -> None:
    rec = _price(source_record_id="P-1", source_payload_hash=HASH_1)
    write_batch(seeded_session, [rec], dry_run=False)
    row = seeded_session.execute(select(FactPriceDaily)).scalar_one()
    assert row.source_record_id == "P-1" and row.source_payload_hash == HASH_1
    report = write_batch(seeded_session, [rec], dry_run=False)  # exact replay
    assert report.idempotent == 1 and report.inserted == 0
    assert _count(seeded_session, FactPriceDaily) == 1  # no duplicate


def test_daily_same_provenance_changed_value_is_conflict(seeded_session: Session) -> None:
    write_batch(seeded_session, [_price(source_record_id="P-1", source_payload_hash=HASH_1, value=100)], dry_run=False)
    report = write_batch(
        seeded_session, [_price(source_record_id="P-1", source_payload_hash=HASH_1, value=200)], dry_run=False
    )
    assert report.conflict == 1 and report.committed is False
    assert report.items[0].get("conflict_kind") == "provenance"
    assert float(seeded_session.execute(select(FactPriceDaily)).scalar_one().value) == 100.0


def test_daily_provenance_identity_includes_data_source(seeded_session: Session) -> None:
    # Same source_record_id but a DIFFERENT data source must NOT be read as a replay:
    # provenance identity = (table, data_source_key, source_record_id). data_source_key
    # is not in the daily grain, so the SAME grain with a different value still conflicts
    # at the grain level (provenance never bypasses a grain conflict).
    write_batch(
        seeded_session, [_price(data_source_code="manual", source_record_id="P-1", value=100)], dry_run=False
    )
    report = write_batch(
        seeded_session, [_price(data_source_code="internal", source_record_id="P-1", value=200)], dry_run=False
    )
    assert report.conflict == 1 and report.inserted == 0 and report.committed is False
    assert report.items[0].get("conflict_kind") == "grain"
    assert _count(seeded_session, FactPriceDaily) == 1
