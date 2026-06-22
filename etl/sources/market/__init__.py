"""Market (price) source — Phase 3A stub. No network, no credentials."""

from __future__ import annotations

from collections.abc import Iterable

from etl.contracts import FactFamily, NormalizedRecord
from etl.sources.base import BaseSource


class MarketSource(BaseSource):
    """Feeds fact_price_daily. Real exchange/spot connectors land in a later phase."""

    source_code = "manual"
    family = FactFamily.price_daily

    def collect(self) -> Iterable[NormalizedRecord]:
        return []
