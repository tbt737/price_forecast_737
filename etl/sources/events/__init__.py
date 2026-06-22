"""Event-risk source — Phase 3A stub. No network, no credentials."""

from __future__ import annotations

from collections.abc import Iterable

from etl.contracts import FactFamily, NormalizedRecord
from etl.sources.base import BaseSource


class EventRiskSource(BaseSource):
    """Feeds fact_event_risk. Real weather-shock/geopolitics connectors land in a later phase."""

    source_code = "unknown"
    family = FactFamily.event_risk

    def collect(self) -> Iterable[NormalizedRecord]:
        return []
