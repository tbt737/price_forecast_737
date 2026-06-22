"""ETL foundation for the Multi-Commodity Quant Forecasting Platform (Phase 3A).

This package is the *safe skeleton* only — contracts, validation, dry-run mapping,
and stub source adapters. It performs NO external ingestion, no network calls, no
credentials, and never writes fact rows. Real connectors and real loaders land in
later phases.

Everything is generic: records are keyed on ``commodity_code``, ``region_code``,
``instrument_code``, ``data_source_code``, ``metric_code``/``indicator_code`` — no
single commodity is special-cased.
"""

from etl.contracts import APPROVED_FACT_TABLES, FACT_FAMILIES, FactFamily, NormalizedRecord
from etl.mapping import DryRunReport, MappingResult, dry_run, map_record
from etl.validation import ErrorCode, Severity, ValidationIssue, ValidationResult, validate_record

__all__ = [
    "FactFamily",
    "FACT_FAMILIES",
    "APPROVED_FACT_TABLES",
    "NormalizedRecord",
    "ErrorCode",
    "Severity",
    "ValidationIssue",
    "ValidationResult",
    "validate_record",
    "MappingResult",
    "DryRunReport",
    "map_record",
    "dry_run",
]
