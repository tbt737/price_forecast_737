"""Dry-run mapping: normalized record -> target fact-table payload.

DRY-RUN ONLY. These functions validate, normalize, and build the payload shape for
the approved fact table, then return a report. They take NO database session and
NEVER insert. Surrogate-key resolution (codes -> *_key) is a later phase.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from etl.contracts import APPROVED_FACT_TABLES, FactFamily, NormalizedRecord
from etl.validation import ValidationResult, validate_record

_PRICE_ATTRS = ("open", "high", "low", "close", "settle", "volume", "open_interest")


@dataclass
class MappingResult:
    ok: bool
    target_table: str | None
    payload: dict[str, Any] | None
    validation: ValidationResult


def map_record(record: NormalizedRecord) -> MappingResult:
    """Validate + map one record to a target fact payload. Never inserts."""
    spec = record.spec()
    validation = validate_record(record)
    target = spec.target_table if spec else None

    # Defensive: a target must be one of the approved fact tables.
    if spec is not None and target not in APPROVED_FACT_TABLES:  # pragma: no cover - spec guarantees this
        return MappingResult(False, None, None, validation)

    if spec is None or not validation.ok:
        return MappingResult(False, target, None, validation)

    payload: dict[str, Any] = {
        "data_source_code": record.data_source_code,
        "release_date": record.release_date,
        "value": record.value,
        "unit": record.unit,
        "revision": record.revision,
        spec.code_field: record.code(),
    }
    if record.commodity_code is not None or spec.requires_commodity:
        payload["commodity_code"] = record.commodity_code
    if record.region_code is not None or spec.requires_region:
        payload["region_code"] = record.region_code

    if spec.periodic:
        payload["period_start"] = record.period_start
        payload["period_end"] = record.period_end
    elif spec.date_field:
        payload[spec.date_field] = record.observation_date

    if spec.family is FactFamily.price_daily:
        payload["currency"] = record.currency
        for attr in _PRICE_ATTRS:
            if attr in record.attributes:
                payload[attr] = record.attributes[attr]

    return MappingResult(True, target, payload, validation)


@dataclass
class DryRunReport:
    total: int = 0
    valid: int = 0
    invalid: int = 0
    results: list[MappingResult] = field(default_factory=list)

    @property
    def inserted(self) -> int:
        """A dry-run NEVER writes facts — always zero."""
        return 0

    @property
    def error_codes(self) -> set[str]:
        codes: set[str] = set()
        for res in self.results:
            codes |= {c.value for c in res.validation.error_codes}
        return codes


def dry_run(records: Iterable[NormalizedRecord]) -> DryRunReport:
    """Map a batch of records in dry-run mode. Inserts nothing; returns a report."""
    report = DryRunReport()
    for record in records:
        result = map_record(record)
        report.total += 1
        report.results.append(result)
        if result.ok:
            report.valid += 1
        else:
            report.invalid += 1
    return report
