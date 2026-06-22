"""Batch planner report — aggregates dry-run InsertPlans into an auditable summary.

`plan_batch()` runs the existing `InsertPlanner` over a batch of records (one
resolver per batch → batch-scoped cache, discarded afterwards) and returns a
`BatchPlanReport`. It writes no facts. With ``simulate=True`` it additionally runs
the existing SAVEPOINT rollback simulation to prove insertability while persisting
nothing.

The report is deterministic (stable input order, sorted aggregate keys, no
``now()``/random) and leak-safe: by default it carries only metadata (families,
target tables, error/warning codes, booleans, counts) — never raw payload values
or resolved surrogate keys.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.planner import InsertPlan, InsertPlanner, simulate_and_rollback
from etl.validation import validate_record


def _family_bucket() -> dict[str, int]:
    return {"planned": 0, "would_insert": 0, "conflict": 0, "rejected": 0}


def _warning_codes(record: NormalizedRecord) -> list[str]:
    # Warnings come from validation only (resolution issues are all errors).
    return sorted({i.code.value for i in validate_record(record).warnings})


@dataclass
class BatchPlanReport:
    total: int
    would_insert: int
    rejected: int
    conflicts: int
    by_family: dict[str, dict[str, int]]
    by_target: dict[str, int]
    by_error_code: dict[str, int]
    by_warning_code: dict[str, int]
    source_code: str | None
    items: list[dict[str, Any]] = field(default_factory=list)
    simulation: dict[str, Any] | None = None

    @classmethod
    def from_plans(
        cls,
        plans: list[InsertPlan],
        *,
        source_code: str | None = None,
        simulation: dict[str, Any] | None = None,
    ) -> BatchPlanReport:
        by_family = {fam.value: _family_bucket() for fam in FactFamily}
        by_target: Counter[str] = Counter()
        by_error: Counter[str] = Counter()
        by_warning: Counter[str] = Counter()
        items: list[dict[str, Any]] = []
        would = rejected = conflicts = 0

        for index, plan in enumerate(plans):
            fam = plan.record.family.value
            bucket = by_family.setdefault(fam, _family_bucket())
            bucket["planned"] += 1

            error_codes = sorted(plan.error_codes)
            warning_codes = _warning_codes(plan.record)
            is_rejected = bool(plan.errors)
            is_conflict = plan.conflict is True

            if is_rejected:
                rejected += 1
                bucket["rejected"] += 1
            elif is_conflict:
                conflicts += 1
                bucket["conflict"] += 1
            if plan.would_insert:
                would += 1
                bucket["would_insert"] += 1

            if plan.target_table:
                by_target[plan.target_table] += 1
            by_error.update(error_codes)
            by_warning.update(warning_codes)

            items.append(
                {
                    "index": index,
                    "family": fam,
                    "target_table": plan.target_table,
                    "would_insert": plan.would_insert,
                    "conflict": plan.conflict,
                    "error_codes": error_codes,
                    "warning_codes": warning_codes,
                }
            )

        return cls(
            total=len(plans),
            would_insert=would,
            rejected=rejected,
            conflicts=conflicts,
            by_family=by_family,
            by_target=dict(sorted(by_target.items())),
            by_error_code=dict(sorted(by_error.items())),
            by_warning_code=dict(sorted(by_warning.items())),
            source_code=source_code,
            items=items,
            simulation=simulation,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (only primitives, lists, and dicts of them)."""
        data: dict[str, Any] = {
            "totals": {
                "total": self.total,
                "would_insert": self.would_insert,
                "rejected": self.rejected,
                "conflicts": self.conflicts,
            },
            "by_family": self.by_family,
            "by_target": self.by_target,
            "by_error_code": self.by_error_code,
            "source_code": self.source_code,
            "items": self.items,
        }
        if self.by_warning_code:
            data["by_warning_code"] = self.by_warning_code
        if self.simulation is not None:
            data["simulation"] = self.simulation
        return data

    def summary(self) -> str:
        """One-screen human-readable summary."""
        src = self.source_code or "-"
        lines = [
            f"Batch plan report (source={src}): {self.total} records → "
            f"{self.would_insert} would-insert, {self.rejected} rejected, {self.conflicts} conflict",
        ]
        if self.by_error_code:
            top = ", ".join(f"{code}×{n}" for code, n in self.by_error_code.items())
            lines.append(f"  errors:   {top}")
        if self.by_warning_code:
            top = ", ".join(f"{code}×{n}" for code, n in self.by_warning_code.items())
            lines.append(f"  warnings: {top}")
        if self.simulation is not None:
            persisted = self.simulation.get("persisted_change")
            lines.append(
                f"  simulation: inserted_in_savepoint="
                f"{self.simulation.get('inserted_in_savepoint')} persisted_change={persisted}"
            )
        return "\n".join(lines)


def plan_batch(
    session: Session,
    records: Iterable[NormalizedRecord],
    *,
    source_code: str | None = None,
    simulate: bool = False,
) -> BatchPlanReport:
    """Plan a batch of records (dry-run, no writes) and return a report.

    A single ``InsertPlanner`` (hence one ``ReferenceResolver``) is created per
    batch, so its lookup cache is batch-scoped and discarded when this returns.
    """
    records = list(records)
    planner = InsertPlanner(session)
    plans = [planner.plan(record) for record in records]

    simulation: dict[str, Any] | None = None
    if simulate:
        sim = simulate_and_rollback(session, records)
        simulation = {
            "inserted_in_savepoint": sim.inserted_in_savepoint,
            "persisted_change": sim.persisted_change,
            "counts_before": sim.counts_before,
            "counts_after": sim.counts_after,
        }

    return BatchPlanReport.from_plans(plans, source_code=source_code, simulation=simulation)
