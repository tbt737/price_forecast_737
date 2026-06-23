"""Integration: Phase 4C-A connector/ETL boundary provenance gate (DB stays nullable)."""

from __future__ import annotations

from dataclasses import replace

from app.models import FactSupplyDemandPeriodic
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.provenance import (
    attach_provenance,
    canonical_payload_hash,
    gate_record,
    gate_records,
    is_valid_payload_hash,
    make_source_record_id,
)
from etl.sources.fixture import load_family_fixture
from etl.validation import ErrorCode
from etl.writer import write_batch

RAW = {
    "data_source_code": "manual", "commodity_code": "ALPHA", "metric_code": "ending_stocks",
    "period_start": "2025-01-01", "period_end": "2025-01-31", "release_date": "2025-02-10", "value": 100.0,
}


def _connector_sd(raw: dict, *, key: int = 0) -> NormalizedRecord:
    """Mimic a connector: raw payload -> record -> deterministic provenance."""
    rec = NormalizedRecord.from_dict(FactFamily.supply_demand_periodic, raw)
    return attach_provenance(rec, raw, source_code=raw.get("data_source_code") or "manual", origin="unit", key=key)


def _codes(record: NormalizedRecord) -> set[str]:
    return {issue.code.value for issue in gate_record(record)}


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# ── deterministic hash helper ─────────────────────────────────────────────────
def test_hash_is_deterministic_and_key_order_independent() -> None:
    a = {"x": 1, "y": 2, "release_date": "2025-01-01"}
    b = {"release_date": "2025-01-01", "y": 2, "x": 1}  # reordered keys
    assert canonical_payload_hash(a) == canonical_payload_hash(b)
    assert is_valid_payload_hash(canonical_payload_hash(a))  # 64-char lowercase hex


def test_hash_changes_when_payload_changes() -> None:
    a = {"x": 1, "y": 2}
    c = {"x": 1, "y": 3}
    assert canonical_payload_hash(a) != canonical_payload_hash(c)


def test_hash_excludes_provenance_metadata() -> None:
    base = {"x": 1, "value": 100.0}
    wrapped = {**base, "source_record_id": "manual:unit:0", "source_payload_hash": "deadbeef"}
    assert canonical_payload_hash(base) == canonical_payload_hash(wrapped)


def test_source_record_id_is_deterministic_not_random() -> None:
    assert make_source_record_id("manual", "feed", 7) == "manual:feed:7"
    assert make_source_record_id("manual", "feed", 7) == make_source_record_id("manual", "feed", 7)


# ── connector gate: fail-closed ───────────────────────────────────────────────
def test_gate_accepts_valid_connector_record() -> None:
    assert gate_record(_connector_sd(RAW)) == []


def test_gate_rejects_missing_source_record_id() -> None:
    rec = replace(_connector_sd(RAW), source_record_id=None)
    assert ErrorCode.MISSING_SOURCE_RECORD_ID.value in _codes(rec)


def test_gate_rejects_missing_source_payload_hash() -> None:
    rec = replace(_connector_sd(RAW), source_payload_hash=None)
    assert ErrorCode.MISSING_SOURCE_PAYLOAD_HASH.value in _codes(rec)


def test_gate_rejects_invalid_source_payload_hash() -> None:
    for bad in ("not-a-hash", "ABCDEF", canonical_payload_hash(RAW).upper(), canonical_payload_hash(RAW)[:63]):
        rec = replace(_connector_sd(RAW), source_payload_hash=bad)
        assert ErrorCode.INVALID_SOURCE_PAYLOAD_HASH.value in _codes(rec)


def test_gate_rejects_missing_data_source() -> None:
    rec = replace(_connector_sd(RAW), data_source_code=None)
    assert ErrorCode.MISSING_SOURCE.value in _codes(rec)


def test_gate_records_partitions_accepted_and_rejected() -> None:
    good = _connector_sd(RAW, key=0)
    bad = replace(_connector_sd(RAW, key=1), source_record_id=None)
    report = gate_records([good, bad])
    assert report.total == 2 and not report.ok
    assert report.accepted == [good]
    assert ErrorCode.MISSING_SOURCE_RECORD_ID.value in report.error_codes()


# ── fixture connector produces stable provenance for every row ────────────────
def test_fixture_source_emits_provenance_for_all_rows() -> None:
    for fam in FactFamily:
        report = load_family_fixture(fam).gate()
        assert report.ok and len(report.accepted) == report.total  # all rows carry provenance
        for rec in report.accepted:
            assert rec.source_record_id and is_valid_payload_hash(rec.source_payload_hash)


def test_fixture_provenance_is_stable_across_collects() -> None:
    first = {r.source_record_id: r.source_payload_hash for r in load_family_fixture(FactFamily.price_daily).collect()}
    second = {r.source_record_id: r.source_payload_hash for r in load_family_fixture(FactFamily.price_daily).collect()}
    assert first == second and first  # deterministic id + hash run-to-run


# ── valid connector record flows through writer + replay is idempotent ────────
def test_connector_record_flows_through_writer_and_persists_provenance(seeded_session: Session) -> None:
    rec = _connector_sd(RAW)
    assert gate_record(rec) == []  # passes the boundary gate
    report = write_batch(seeded_session, [rec], dry_run=False)
    assert report.inserted == 1 and report.committed is True
    row = seeded_session.execute(select(FactSupplyDemandPeriodic)).scalar_one()
    assert row.source_record_id == "manual:unit:0"
    assert row.source_payload_hash == canonical_payload_hash(RAW)


def test_replay_same_connector_identity_is_idempotent(seeded_session: Session) -> None:
    write_batch(seeded_session, [_connector_sd(RAW)], dry_run=False)
    report = write_batch(seeded_session, [_connector_sd(RAW)], dry_run=False)  # re-ingest same source record
    assert report.idempotent == 1 and report.inserted == 0
    assert _count(seeded_session, FactSupplyDemandPeriodic) == 1  # no duplicate


# ── DB provenance columns remain nullable (no NOT NULL in 4C-A) ───────────────
def test_provenance_columns_remain_nullable(seeded_session: Session) -> None:
    cols = {c["name"]: c for c in inspect(seeded_session.get_bind()).get_columns("fact_supply_demand_periodic")}
    assert cols["source_record_id"]["nullable"] is True
    assert cols["source_payload_hash"]["nullable"] is True
