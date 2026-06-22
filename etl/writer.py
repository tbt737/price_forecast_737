"""Transaction-safe ETL write path (Phase 4A).

Turns Phase 3B/3C insert plans into a controlled DB write with explicit dry-run vs
write modes, fail-closed lineage, deterministic idempotency, conflict safety, and
atomic batch rollback. Still fixture/mock only — no external ingestion.

Semantics (per record, classified against the DB *and* the in-batch staged set):
  * REJECTED   — validation/resolution failed (incl. missing/unknown source). No write.
  * NEW        — no row for this canonical identity → insert.
  * IDEMPOTENT — a row with the same canonical identity AND the same normalized
                 non-grain values already exists → no-op (no duplicate).
  * CONFLICT   — same canonical identity but different normalized values → no write.

Canonical identity is derived deterministically from the resolved unique grain
(which already includes ``data_source_key`` for periodic facts and the
instrument/region/metric/date fields per Phase 2) — NO new DB column is added.

Batch atomicity: in write mode, if ANY record is REJECTED or CONFLICT, the whole
batch is rolled back (no partial writes). Only batches that are entirely NEW/
IDEMPOTENT commit.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from etl.conflicts import TARGET_MODELS, find_existing_row
from etl.contracts import NormalizedRecord
from etl.planner import InsertPlan, InsertPlanner


class WriteOutcome(enum.StrEnum):
    new = "new"
    idempotent = "idempotent"
    conflict = "conflict"
    rejected = "rejected"


def canonical_identity(plan: InsertPlan) -> tuple[Any, ...]:
    """Deterministic identity for a plan: (target_table, sorted grain items).

    Mirrors the DB unique grain exactly, so two records collide here iff they
    collide in the database.
    """
    grain = plan.grain or {}
    return (plan.target_table, *sorted((key, grain[key]) for key in grain))


def _value_fields(plan: InsertPlan) -> dict[str, Any]:
    """Payload columns that are NOT part of the grain (the comparable 'value')."""
    grain_keys = set(plan.grain or {})
    payload = plan.payload or {}
    return {key: value for key, value in payload.items() if key not in grain_keys}


def _normalize(value: Any) -> Any:
    """Normalize for value comparison: numerics → Decimal; others unchanged."""
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


def _existing_values(session: Session, plan: InsertPlan) -> dict[str, Any] | None:
    """Value fields of the existing row for this plan's grain, or None if absent."""
    row = find_existing_row(session, plan.record.family, plan.grain or {})
    if row is None:
        return None
    return {key: getattr(row, key) for key in _value_fields(plan)}


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


def _classify(session: Session, plan: InsertPlan, staged: dict[tuple[Any, ...], dict[str, Any]]) -> WriteOutcome:
    if plan.errors:
        return WriteOutcome.rejected
    identity = canonical_identity(plan)
    values = _value_fields(plan)
    existing = _existing_values(session, plan)
    if existing is None:
        existing = staged.get(identity)
    if existing is None:
        staged[identity] = values
        return WriteOutcome.new
    return WriteOutcome.idempotent if _values_equal(existing, values) else WriteOutcome.conflict


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

    staged: dict[tuple[Any, ...], dict[str, Any]] = {}
    outcomes = [_classify(session, plan, staged) for plan in plans]

    report = WriteReport(mode="dry_run" if dry_run else "write", planned=len(plans))
    for index, (plan, outcome) in enumerate(zip(plans, outcomes, strict=True)):
        if outcome is WriteOutcome.idempotent:
            report.idempotent += 1
        elif outcome is WriteOutcome.conflict:
            report.conflict += 1
        elif outcome is WriteOutcome.rejected:
            report.rejected += 1
        report.items.append(
            {
                "index": index,
                "family": plan.record.family.value,
                "target_table": plan.target_table,
                "outcome": outcome.value,
                "error_codes": sorted(plan.error_codes),
            }
        )

    if dry_run:
        report.committed = None
        return report

    # Write mode — atomic batch.
    blocked = any(o in (WriteOutcome.rejected, WriteOutcome.conflict) for o in outcomes)
    if blocked:
        session.rollback()  # discard anything pending; no partial write
        report.committed = False
        return report

    try:
        for plan, outcome in zip(plans, outcomes, strict=True):
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
