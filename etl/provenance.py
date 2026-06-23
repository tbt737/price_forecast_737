"""Phase 4C-A — connector/ETL boundary provenance gate (DB stays nullable).

Provenance enforcement lives at the *connector boundary* (where a connector / mock
fixture / raw payload becomes a ``NormalizedRecord``), NOT in the global
``validate_record`` used by the planner/writer. That keeps Phase 4A/4B behaviour for
legacy/direct records (no provenance required) while requiring connector-originated
records to carry a deterministic, stable source identity before they reach the
planner/writer.

This module:
* derives a **deterministic** ``source_payload_hash`` (SHA-256 of canonical JSON —
  key-order independent, no volatile fields, no Python ``repr``/object identity);
* derives a **stable** ``source_record_id`` (``<source_code>:<origin>:<key>`` — never a
  random UUID, never a local auto-increment DB id);
* ``gate_record``/``gate_records``: fail-closed checks that reject a connector record
  missing ``data_source_code`` / ``source_record_id`` / ``source_payload_hash`` or
  carrying a malformed hash.

No DB writes, no schema change, no NOT NULL — the columns stay nullable.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from etl.contracts import NormalizedRecord
from etl.validation import ErrorCode, ValidationIssue

#: a valid source payload hash is a 64-char lowercase SHA-256 hex digest.
_SHA256_HEX = re.compile(r"\A[0-9a-f]{64}\Z")

#: fields that are provenance metadata, excluded from the hashed source payload so
#: attaching provenance never changes the hash of the underlying data.
_PROVENANCE_FIELDS = ("source_record_id", "source_payload_hash")


def canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 hex of a source payload.

    Canonical JSON: ``sort_keys`` (key-order independent), tight separators, UTF-8,
    ``default=str`` so dates/Decimals serialize stably. Provenance metadata fields are
    excluded so the hash describes the *data*, not the lineage wrapper.
    """
    material = {k: v for k, v in payload.items() if k not in _PROVENANCE_FIELDS}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def is_valid_payload_hash(value: str | None) -> bool:
    """True iff ``value`` is a 64-char lowercase SHA-256 hex digest."""
    return value is not None and _SHA256_HEX.match(value) is not None


def make_source_record_id(source_code: str, *parts: Any) -> str:
    """Build a deterministic ``<source_code>:<part>:<part>...`` identity.

    Never random, never a local DB id — derived from stable source attributes only.
    """
    return ":".join(str(part) for part in (source_code, *parts))


def attach_provenance(
    record: NormalizedRecord,
    payload: Mapping[str, Any],
    *,
    source_code: str,
    origin: str,
    key: Any,
) -> NormalizedRecord:
    """Return ``record`` with deterministic provenance filled in where missing.

    Honours any provenance the source already supplied (e.g. a real external id);
    otherwise derives a stable id from ``(source_code, origin, key)`` and hashes the
    raw ``payload``.
    """
    sid = record.source_record_id or make_source_record_id(source_code, origin, key)
    payload_hash = record.source_payload_hash or canonical_payload_hash(payload)
    return replace(record, source_record_id=sid, source_payload_hash=payload_hash)


def gate_record(record: NormalizedRecord) -> list[ValidationIssue]:
    """Fail-closed provenance gate for a connector-originated record.

    Returns the blocking issues (empty list = accepted). Does not raise; callers
    decide whether to drop or surface. Never silently fabricates provenance.
    """
    issues: list[ValidationIssue] = []
    if not record.data_source_code:
        issues.append(ValidationIssue(ErrorCode.MISSING_SOURCE, "connector record requires data_source_code"))
    if not record.source_record_id:
        issues.append(
            ValidationIssue(ErrorCode.MISSING_SOURCE_RECORD_ID, "connector record requires source_record_id")
        )
    if not record.source_payload_hash:
        issues.append(
            ValidationIssue(ErrorCode.MISSING_SOURCE_PAYLOAD_HASH, "connector record requires source_payload_hash")
        )
    elif not is_valid_payload_hash(record.source_payload_hash):
        issues.append(
            ValidationIssue(
                ErrorCode.INVALID_SOURCE_PAYLOAD_HASH,
                "source_payload_hash must be a 64-char lowercase sha256 hex digest",
            )
        )
    return issues


@dataclass
class ConnectorGateReport:
    """Outcome of gating a batch of connector records (fail-closed)."""

    accepted: list[NormalizedRecord]
    rejected: list[tuple[NormalizedRecord, list[ValidationIssue]]]

    @property
    def ok(self) -> bool:
        return not self.rejected

    @property
    def total(self) -> int:
        return len(self.accepted) + len(self.rejected)

    def error_codes(self) -> set[str]:
        return {issue.code.value for _record, issues in self.rejected for issue in issues}


def gate_records(records: Iterable[NormalizedRecord]) -> ConnectorGateReport:
    """Apply :func:`gate_record` to a batch; partition into accepted/rejected."""
    accepted: list[NormalizedRecord] = []
    rejected: list[tuple[NormalizedRecord, list[ValidationIssue]]] = []
    for record in records:
        issues = gate_record(record)
        if issues:
            rejected.append((record, issues))
        else:
            accepted.append(record)
    return ConnectorGateReport(accepted, rejected)
