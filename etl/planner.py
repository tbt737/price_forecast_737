"""Insert planner + dry-run-to-DB validation.

Turns a normalized ETL record into a *planned* fact insert: validate -> resolve
references -> build the resolved DB payload -> pre-check unique-grain conflict ->
report. It NEVER persists a fact:

* ``InsertPlanner.plan()`` is plan-only — it issues SELECTs (resolution + conflict)
  but no writes.
* ``simulate_and_rollback()`` actually inserts the would-insert plans inside a
  SAVEPOINT and then rolls back, proving the rows are insertable while leaving the
  persisted fact-table counts unchanged.

No external network, no secrets, not commodity-specific.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from etl.conflicts import GRAIN_FIELDS, TARGET_MODELS, conflict_exists, grain_values
from etl.contracts import FACT_FAMILIES, FactFamily, FamilySpec, NormalizedRecord
from etl.resolution import ReferenceResolver, ResolutionResult
from etl.validation import ValidationIssue, validate_record

_PRICE_ATTRS = ("open", "high", "low", "close", "settle", "volume", "open_interest")


def build_payload(record: NormalizedRecord, resolution: ResolutionResult, spec: FamilySpec) -> dict[str, Any]:
    """Build the resolved (surrogate-key) insert payload for the target fact table."""
    payload: dict[str, Any] = {
        "data_source_key": resolution.data_source_key,
        "release_date": record.release_date,
        "value": record.value,
        "unit": record.unit,
        "revision": record.revision,
    }
    if spec.requires_commodity or record.commodity_code:
        payload["commodity_key"] = resolution.commodity_key
    if spec.requires_region or record.region_code:
        payload["region_key"] = resolution.region_key

    if spec.periodic:
        payload["period_start"] = record.period_start
        payload["period_end"] = record.period_end
    elif spec.date_field:
        payload[spec.date_field] = record.observation_date

    if spec.family is FactFamily.price_daily:
        payload["market_instrument_key"] = resolution.market_instrument_key
        payload["currency"] = record.currency
        for attr in _PRICE_ATTRS:
            if attr in record.attributes:
                payload[attr] = record.attributes[attr]
    else:
        # weather/sd/event -> metric_code column; macro/logistics -> indicator_code column
        payload[spec.code_field] = record.code()

    return payload


@dataclass
class InsertPlan:
    record: NormalizedRecord
    target_table: str | None
    resolved_keys: dict[str, int | None]
    payload: dict[str, Any] | None
    grain: dict[str, Any] | None
    errors: list[ValidationIssue] = field(default_factory=list)
    conflict: bool | None = None  # None = not checked (no session / invalid record)

    @property
    def would_insert(self) -> bool:
        return not self.errors and self.conflict is False

    @property
    def grain_fields(self) -> tuple[str, ...]:
        return GRAIN_FIELDS.get(self.record.family, ())

    @property
    def error_codes(self) -> set[str]:
        return {i.code.value for i in self.errors}


class InsertPlanner:
    """Plans fact inserts against the live dimensions. Plan-only: never writes."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._resolver = ReferenceResolver(session)

    def plan(self, record: NormalizedRecord) -> InsertPlan:
        spec = record.spec()
        target = spec.target_table if spec else None

        validation = validate_record(record)
        resolution = self._resolver.resolve(record)
        errors = list(validation.errors) + list(resolution.issues)
        resolved_keys = resolution.resolved_keys()

        # Source lineage guarantee: no source -> no plan, no insert.
        if spec is None or errors:
            return InsertPlan(record, target, resolved_keys, None, None, errors, None)

        payload = build_payload(record, resolution, spec)
        grain = grain_values(record, resolution)
        conflict = conflict_exists(self._session, record.family, grain)
        return InsertPlan(record, target, resolved_keys, payload, grain, errors, conflict)


def _fact_counts(session: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for family, model in TARGET_MODELS.items():
        counts[FACT_FAMILIES[family].target_table] = session.scalar(select(func.count()).select_from(model)) or 0
    return counts


@dataclass
class SimulationReport:
    plans: list[InsertPlan]
    inserted_in_savepoint: int
    counts_before: dict[str, int]
    counts_within: dict[str, int]
    counts_after: dict[str, int]

    @property
    def persisted_change(self) -> bool:
        return self.counts_before != self.counts_after  # must be False (rollback)


def simulate_and_rollback(session: Session, records: Iterable[NormalizedRecord]) -> SimulationReport:
    """Plan records, insert the would-insert ones inside a SAVEPOINT, then roll back.

    Proves the plans are insertable AND that nothing persists (counts unchanged).
    """
    planner = InsertPlanner(session)
    plans = [planner.plan(record) for record in records]
    counts_before = _fact_counts(session)

    nested = session.begin_nested()
    inserted = 0
    try:
        for plan in plans:
            if plan.would_insert and plan.payload is not None:
                model = TARGET_MODELS[plan.record.family]
                session.add(model(**plan.payload))
                inserted += 1
        session.flush()
        counts_within = _fact_counts(session)
    finally:
        nested.rollback()

    counts_after = _fact_counts(session)
    return SimulationReport(plans, inserted, counts_before, counts_within, counts_after)
