"""Macro source — Phase 3A stub. No network, no credentials."""

from __future__ import annotations

from collections.abc import Iterable

from etl.contracts import FactFamily, NormalizedRecord
from etl.sources.base import BaseSource


class MacroSource(BaseSource):
    """Feeds fact_macro_daily. Real FX/rates/macro connectors land in a later phase."""

    source_code = "unknown"
    family = FactFamily.macro_daily

    def collect(self) -> Iterable[NormalizedRecord]:
        return []
