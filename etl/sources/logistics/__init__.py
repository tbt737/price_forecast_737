"""Logistics (freight) source — Phase 3A stub. No network, no credentials."""

from __future__ import annotations

from collections.abc import Iterable

from etl.contracts import FactFamily, NormalizedRecord
from etl.sources.base import BaseSource


class LogisticsSource(BaseSource):
    """Feeds fact_logistics_periodic. Real freight-index connectors land in a later phase."""

    source_code = "unknown"
    family = FactFamily.logistics_periodic

    def collect(self) -> Iterable[NormalizedRecord]:
        return []
