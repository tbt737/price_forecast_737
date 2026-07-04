"""NOAA Oceanic Nino Index (ONI) events connector (feeds ``fact_event_risk``).

Config-driven (``configs/ingestion/sources.yaml`` ``events:``).
Fetches ONI values which indicate El Nino / La Nina events.
"""

from __future__ import annotations

import logging
import urllib.request
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import EventRiskSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource

logger = logging.getLogger(__name__)

#: fetch() -> [{"date": date, "value": float}, ...]
OniFetch = Callable[[], list[dict[str, Any]]]

def _parse_oni_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Parse NOAA ONI ASCII rows: ``Year SEAS Total_Mean Anom`` (e.g. ``1950 DJF 24.72 -1.53``)."""
    # Month to numerical mapping for the end of the 3-month season
    # e.g., DJF ends in February (2), JFM ends in March (3)
    seas_map = {
        "DJF": 2, "JFM": 3, "FMA": 4, "MAM": 5, "AMJ": 6, "MJJ": 7,
        "JJA": 8, "JAS": 9, "ASO": 10, "SON": 11, "OND": 12, "NDJ": 1,
    }
    rows: list[dict[str, Any]] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            year = int(parts[0])
            anom = float(parts[3])
        except ValueError:
            continue
        seas = parts[1]
        month = seas_map.get(seas)
        if not month:
            continue
        # If season is NDJ, the year of the end month (Jan) is year + 1
        if seas == "NDJ":
            year += 1
        rows.append({"date": date(year, month, 1), "value": anom})
    return rows


def _noaa_oni_fetch() -> list[dict[str, Any]]:
    url = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"NOAA ONI fetch failed with HTTP {response.status}")
        lines = response.read().decode("utf-8").splitlines()
    rows = _parse_oni_lines(lines)
    if not rows:
        raise RuntimeError("NOAA ONI response contained no parseable rows")
    return rows

class NoaaOniSource(BaseSource):
    family = FactFamily.event_risk

    def __init__(self, specs: list[EventRiskSpec], *, fetch: OniFetch | None = None) -> None:
        self._specs = specs
        self._fetch = fetch or _noaa_oni_fetch
        self.source_code = specs[0].source_code if specs else "NOAA"

    def collect(self) -> Iterable[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        if not self._specs:
            return records

        spec = next((s for s in self._specs if s.metric_code == "el_nino_la_nina"), None)
        if not spec:
            return records

        # Fail soft: NOAA is a flaky, non-critical exogenous source. If the fetch is
        # unavailable / empty / unparseable, skip the event_risk family for this run
        # rather than raising and killing the whole (price-critical) ingest. Only the
        # expected network/HTTP/empty/parse cases are caught — programmer errors propagate.
        try:
            rows = list(self._fetch())
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("NOAA ONI fetch unavailable (%s) — skipping event_risk this run", exc)
            return records

        for row in rows:
            obs: date = row["date"]
            payload = {
                "metric_code": spec.metric_code,
                "data_source_code": spec.source_code,
                "category": spec.category,
                "observation_date": obs.isoformat(),
                "value": row["value"],
            }
            record = NormalizedRecord(
                family=FactFamily.event_risk,
                data_source_code=spec.source_code,
                metric_code=spec.metric_code,
                observation_date=obs,
                # release date is typically the middle of the following month.
                # E.g. JFM is released around mid April. We'll use the end of the month + lag days.
                # A simple approximation: next month + lag days.
                release_date=obs + timedelta(days=31 + spec.release_lag_days),
                value=row["value"],
                unit="degC",
            )
            records.append(
                attach_provenance(
                    record, payload, source_code=spec.source_code, origin="noaa_oni_ascii", key=obs.isoformat()
                )
            )
        return records
