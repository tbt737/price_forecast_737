"""Abstract base for ETL source adapters.

A source declares its ``source_code`` (must map to a ``dim_data_source`` row) and
its ``family``, and yields ``NormalizedRecord``s via ``collect()``. Phase 3A stubs
return nothing. ``dry_run()`` validates + maps whatever ``collect()`` returns
WITHOUT touching any database.
"""

from __future__ import annotations

import abc
from collections.abc import Iterable

from etl.contracts import FactFamily, NormalizedRecord
from etl.mapping import DryRunReport, dry_run
from etl.provenance import ConnectorGateReport, gate_records


class BaseSource(abc.ABC):
    """Base class for all source adapters. No network or credentials in Phase 3A."""

    #: business code that must exist in dim_data_source (e.g. 'manual', 'unknown').
    source_code: str = "unknown"
    #: which fact family this source feeds.
    family: FactFamily

    @abc.abstractmethod
    def collect(self) -> Iterable[NormalizedRecord]:
        """Return normalized records. Phase 3A stubs return an empty list."""
        raise NotImplementedError

    def dry_run(self) -> DryRunReport:
        """Validate + map this source's records in dry-run mode (no DB writes)."""
        return dry_run(self.collect())

    def gate(self) -> ConnectorGateReport:
        """Phase 4C-A connector boundary: collect, then fail-closed on missing/invalid
        provenance. Connector-originated records must carry a deterministic source
        identity before they reach the planner/writer."""
        return gate_records(self.collect())
