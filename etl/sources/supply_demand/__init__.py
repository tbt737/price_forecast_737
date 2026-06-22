"""Supply & demand source — Phase 3A stub. No network, no credentials."""

from __future__ import annotations

from collections.abc import Iterable

from etl.contracts import FactFamily, NormalizedRecord
from etl.sources.base import BaseSource


class SupplyDemandSource(BaseSource):
    """Feeds fact_supply_demand_periodic. Real WASDE/PSD connectors land in a later phase."""

    source_code = "unknown"
    family = FactFamily.supply_demand_periodic

    def collect(self) -> Iterable[NormalizedRecord]:
        return []
