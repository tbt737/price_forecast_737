"""Validation framework for normalized ETL records.

Returns structured issues; never sanitizes, never inserts, never fails open. A
record with any error-severity issue is invalid and must not be mapped to a fact.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from etl.contracts import FactFamily, NormalizedRecord


class ErrorCode(enum.StrEnum):
    MISSING_SOURCE = "MISSING_SOURCE"
    MISSING_RELEASE_DATE = "MISSING_RELEASE_DATE"
    INVALID_PERIOD_RANGE = "INVALID_PERIOD_RANGE"
    UNKNOWN_TARGET_FACT = "UNKNOWN_TARGET_FACT"
    MISSING_COMMODITY = "MISSING_COMMODITY"
    MISSING_REGION = "MISSING_REGION"
    MISSING_INSTRUMENT = "MISSING_INSTRUMENT"
    MISSING_METRIC = "MISSING_METRIC"
    LOOKAHEAD_UNSAFE = "LOOKAHEAD_UNSAFE"


class Severity(enum.StrEnum):
    error = "error"
    warning = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    code: ErrorCode
    message: str
    severity: Severity = Severity.error


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, code: ErrorCode, message: str, severity: Severity = Severity.error) -> None:
        self.issues.append(ValidationIssue(code, message, severity))

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.error]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.warning]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def error_codes(self) -> set[ErrorCode]:
        return {i.code for i in self.errors}


def validate_record(record: NormalizedRecord) -> ValidationResult:
    """Validate a normalized record against its family's contract."""
    result = ValidationResult()
    spec = record.spec()
    if spec is None:
        result.add(ErrorCode.UNKNOWN_TARGET_FACT, f"Unknown fact family: {record.family!r}")
        return result  # cannot validate further without a spec

    # Source lineage is mandatory for EVERY fact (no NULL source for facts).
    if not record.data_source_code:
        result.add(ErrorCode.MISSING_SOURCE, "data_source_code is required — facts must carry source lineage")

    # Point-in-time: release_date (as-of date) is always required.
    if record.release_date is None:
        result.add(ErrorCode.MISSING_RELEASE_DATE, "release_date is required")

    # Dimension requirements that mirror NOT NULL FKs on the target table.
    if spec.requires_commodity and not record.commodity_code:
        result.add(ErrorCode.MISSING_COMMODITY, f"{spec.target_table} requires commodity_code")
    if spec.requires_region and not record.region_code:
        result.add(ErrorCode.MISSING_REGION, f"{spec.target_table} requires region_code")

    # Metric/indicator/instrument code.
    if not record.code():
        if spec.family is FactFamily.price_daily:
            result.add(ErrorCode.MISSING_INSTRUMENT, "instrument_code is recommended for price facts", Severity.warning)
        elif spec.code_required:
            result.add(ErrorCode.MISSING_METRIC, f"{spec.code_field} is required for {spec.target_table}")

    # Period range vs single observation date.
    if spec.periodic:
        if record.period_start is None or record.period_end is None:
            result.add(ErrorCode.INVALID_PERIOD_RANGE, "period_start and period_end are required for periodic facts")
        elif record.period_end < record.period_start:
            result.add(ErrorCode.INVALID_PERIOD_RANGE, "period_end must be on/after period_start")
    elif record.observation_date is None:
        result.add(
            ErrorCode.LOOKAHEAD_UNSAFE,
            f"observation date ({spec.date_field}) is required to verify point-in-time safety",
        )

    # Look-ahead: a value cannot be released before the date it describes.
    ref = record.reference_date()
    if record.release_date is not None and ref is not None and record.release_date < ref:
        result.add(ErrorCode.LOOKAHEAD_UNSAFE, "release_date must be on/after the observation/period-end date")

    return result
