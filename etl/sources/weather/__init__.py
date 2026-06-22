"""Weather source — Phase 3A stub. No network, no credentials."""

from __future__ import annotations

from collections.abc import Iterable

from etl.contracts import FactFamily, NormalizedRecord
from etl.sources.base import BaseSource


class WeatherSource(BaseSource):
    """Feeds fact_weather_daily. Real agroclimatology connectors land in a later phase."""

    source_code = "unknown"
    family = FactFamily.weather_daily

    def collect(self) -> Iterable[NormalizedRecord]:
        return []
