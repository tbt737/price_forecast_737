"""Transaction-safe ETL write path (Phase 4A) + source provenance replay (Phase 4B).

`write_batch` turns Phase 3B/3C insert plans into a controlled DB write with explicit
dry-run vs write modes, fail-closed lineage, deterministic idempotency, conflict
safety, and atomic batch rollback. Still fixture/mock only — no external ingestion.

Per-record classification (against the DB *and* the in-batch staged set):
  * REJECTED   — validation/resolution failed (incl. missing/unknown source). No write.
  * NEW        — no match → insert.
  * IDEMPOTENT — an equivalent row already exists → no-op (no duplicate).
  * CONFLICT   — a matching slot exists with a different value → no write.

Two identities are used, provenance FIRST then grain (provenance never bypasses a
grain conflict):
  * Provenance identity = (target_table, data_source_key, source_record_id) — only
    when the record carries a ``source_record_id`` and a resolved source. Detects
    replay of the *same source record*: same value + same ``source_payload_hash`` →
    idempotent; otherwise PROVENANCE conflict.
  * Grain identity = the Phase 2 unique grain (Phase 4A behaviour, unchanged).
    ``source_record_id``/``source_payload_hash`` are NOT part of the grain and are
    excluded from the grain value comparison, so records without provenance behave
    exactly as in Phase 4A.

Batch atomicity: in write mode, if ANY record is REJECTED or CONFLICT, the whole
batch rolls back (no partial writes).
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from etl.conflicts import TARGET_MODELS, find_existing_row
from etl.contracts import NormalizedRecord
from etl.planner import InsertPlan, InsertPlanner

_PROVENANCE_KEYS = ("source_record_id", "source_payload_hash")


class WriteOutcome(enum.StrEnum):
    new = "new"
    idempotent = "idempotent"
    conflict = "conflict"
    rejected = "rejected"


def canonical_identity(plan: InsertPlan) -> tuple[Any, ...]:
    """Deterministic grain identity: (target_table, sorted grain items).

    Mirrors the DB unique grain exactly, so two records collide here iff they
    collide in the database. Provenance is NOT part of this identity.
    """
    grain = plan.grain or {}
    return (plan.target_table, *sorted((key, grain[key]) for key in grain))


def _value_fields(plan: InsertPlan) -> dict[str, Any]:
    """Payload columns that are NOT grain and NOT provenance (the comparable value)."""
    grain_keys = set(plan.grain or {})
    payload = plan.payload or {}
    return {k: v for k, v in payload.items() if k not in grain_keys and k not in _PROVENANCE_KEYS}


def _normalize(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):  # pragma: no cover - defensive
            return value
    return value


def _values_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = set(left) | set(right)
    return all(_normalize(left.get(key)) == _normalize(right.get(key)) for key in keys)


@dataclass
class _Existing:
    values: dict[str, Any]
    payload_hash: str | None


def _existing(plan: InsertPlan, row: Any) -> _Existing:
    return _Existing({key: getattr(row, key) for key in _value_fields(plan)}, getattr(row, "source_payload_hash", None))


def _existing_by_grain(session: Session, plan: InsertPlan) -> _Existing | None:
    row = find_existing_row(session, plan.record.family, plan.grain or {})
    return _existing(plan, row) if row is not None else None


def _provenance_id(plan: InsertPlan) -> tuple[Any, ...] | None:
    sid = plan.record.source_record_id
    data_source_key = (plan.resolved_keys or {}).get("data_source_key")
    if sid and data_source_key is not None:
        return (plan.target_table, data_source_key, sid)
    return None


def _existing_by_provenance(session: Session, plan: InsertPlan) -> _Existing | None:
    pid = _provenance_id(plan)
    if pid is None:
        return None
    model: Any = TARGET_MODELS[plan.record.family]
    _, data_source_key, sid = pid
    row = session.execute(
        select(model)
        .where(model.data_source_key == data_source_key, model.source_record_id == sid)
        .limit(1)
    ).scalar_one_or_none()
    return _existing(plan, row) if row is not None else None


def _classify(
    session: Session,
    plan: InsertPlan,
    staged_grain: dict[tuple[Any, ...], _Existing],
    staged_prov: dict[tuple[Any, ...], _Existing],
) -> tuple[WriteOutcome, str | None]:
    if plan.errors:
        return WriteOutcome.rejected, None

    values = _value_fields(plan)
    incoming_hash = plan.record.source_payload_hash

    # 1) Provenance-aware replay (only if the record carries source provenance).
    pid = _provenance_id(plan)
    if pid is not None:
        prov = _existing_by_provenance(session, plan) or staged_prov.get(pid)
        if prov is not None:
            same = _values_equal(prov.values, values) and prov.payload_hash == incoming_hash
            return (WriteOutcome.idempotent, None) if same else (WriteOutcome.conflict, "provenance")

    # 2) Grain logic (Phase 4A, unchanged) — provenance never bypasses a grain conflict.
    gid = canonical_identity(plan)
    grain = _existing_by_grain(session, plan) or staged_grain.get(gid)
    if grain is None:
        staged_grain[gid] = _Existing(values, incoming_hash)
        if pid is not None:
            staged_prov[pid] = _Existing(values, incoming_hash)
        return WriteOutcome.new, None
    if _values_equal(grain.values, values):
        return WriteOutcome.idempotent, None
    return WriteOutcome.conflict, "grain"


@dataclass
class WriteReport:
    mode: str  # "dry_run" | "write"
    planned: int = 0
    inserted: int = 0
    idempotent: int = 0
    conflict: int = 0
    rejected: int = 0
    committed: bool | None = None  # None in dry-run (nothing to commit)
    items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "committed": self.committed,
            "totals": {
                "planned": self.planned,
                "inserted": self.inserted,
                "idempotent": self.idempotent,
                "conflict": self.conflict,
                "rejected": self.rejected,
            },
            "items": self.items,
        }

    def summary(self) -> str:
        return (
            f"ETL write [{self.mode}] committed={self.committed}: {self.planned} planned → "
            f"{self.inserted} inserted, {self.idempotent} idempotent, "
            f"{self.conflict} conflict, {self.rejected} rejected"
        )


def write_batch(
    session: Session,
    records: Iterable[NormalizedRecord],
    *,
    dry_run: bool = True,
) -> WriteReport:
    """Plan + classify a batch; in write mode, atomically insert NEW rows.

    Dry-run writes nothing. Write mode commits only if the whole batch is
    NEW/IDEMPOTENT; any REJECTED or CONFLICT rolls back the entire batch.
    """
    records = list(records)
    planner = InsertPlanner(session)
    plans = [planner.plan(record) for record in records]

    staged_grain: dict[tuple[Any, ...], _Existing] = {}
    staged_prov: dict[tuple[Any, ...], _Existing] = {}
    classified = [_classify(session, plan, staged_grain, staged_prov) for plan in plans]

    report = WriteReport(mode="dry_run" if dry_run else "write", planned=len(plans))
    for index, (plan, (outcome, kind)) in enumerate(zip(plans, classified, strict=True)):
        if outcome is WriteOutcome.idempotent:
            report.idempotent += 1
        elif outcome is WriteOutcome.conflict:
            report.conflict += 1
        elif outcome is WriteOutcome.rejected:
            report.rejected += 1
        item: dict[str, Any] = {
            "index": index,
            "family": plan.record.family.value,
            "target_table": plan.target_table,
            "outcome": outcome.value,
            "error_codes": sorted(plan.error_codes),
        }
        if kind is not None:
            item["conflict_kind"] = kind
        report.items.append(item)

    if dry_run:
        report.committed = None
        return report

    # Write mode — atomic batch.
    blocked = any(outcome in (WriteOutcome.rejected, WriteOutcome.conflict) for outcome, _ in classified)
    if blocked:
        session.rollback()  # discard anything pending; no partial write
        report.committed = False
        return report

    try:
        for plan, (outcome, _kind) in zip(plans, classified, strict=True):
            if outcome is WriteOutcome.new:
                session.add(TARGET_MODELS[plan.record.family](**(plan.payload or {})))
                report.inserted += 1
        session.commit()
        report.committed = True
    except Exception:
        session.rollback()
        report.committed = False
        report.inserted = 0
        raise

    return report
