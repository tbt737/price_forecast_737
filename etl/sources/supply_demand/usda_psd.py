"""USDA FAS PSD supply & demand connector (feeds ``fact_supply_demand_periodic``).

Config-driven (``configs/ingestion/sources.yaml`` ``supply_demand:``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta
import json
import urllib.request
from typing import Any

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import SupplyDemandSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource

#: fetch(usda_commodity_id) -> list of dicts (year, attribute_id, value, month_start)
UsdaFetch = Callable[[str], list[dict[str, Any]]]

def _usda_fas_fetch(usda_commodity_id: str) -> list[dict[str, Any]]:
    import os

    api_key = os.environ.get("USDA_FAS_API_KEY")
    if not api_key:
        raise RuntimeError("USDA FAS API connector requires USDA_FAS_API_KEY environment variable")

    url = f"https://apps.fas.usda.gov/OpenDataAPI/api/psd/commodity/{usda_commodity_id}"
    req = urllib.request.Request(url, headers={"API_KEY": api_key, "User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"USDA FAS PSD fetch failed with HTTP {response.status}")
        data = json.loads(response.read().decode("utf-8"))

    if not isinstance(data, list):
        raise RuntimeError("USDA FAS PSD response was not a JSON list")

    rows: list[dict[str, Any]] = []
    for item in data:
        # Example USDA PSD JSON item:
        # {"commodityCode": "0711100", "marketYear": "2024", "calendarYear": "2024",
        #  "month": "10", "attributeId": 28, "value": 1500}
        market_year = int(item.get("marketYear", 0))
        month = int(item.get("month", 1))
        attr_id = int(item.get("attributeId", 0))
        val = float(item.get("value", 0.0))

        if market_year > 0 and attr_id > 0:
            # We assume the marketing year starts on the given month
            try:
                start_date = date(market_year, month, 1)
                rows.append({
                    "attribute_id": attr_id,
                    "market_year": market_year,
                    "start_date": start_date,
                    "value": val
                })
            except ValueError:
                pass

    if not rows:
        raise RuntimeError(f"USDA FAS PSD response for {usda_commodity_id} contained no parseable rows")
    return rows

class UsdaPsdSource(BaseSource):
    family = FactFamily.supply_demand_periodic

    def __init__(self, specs: list[SupplyDemandSpec], *, fetch: UsdaFetch | None = None) -> None:
        self._specs = specs
        self._fetch = fetch or _usda_fas_fetch
        self.source_code = specs[0].source_code if specs else "USDA_FAS"

    def collect(self) -> Iterable[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        for spec in self._specs:
            data = self._fetch(spec.usda_commodity_id)
            if not data:
                continue

            # inverse mapping: attr_id -> metric_code
            attr_map = {v: k for k, v in spec.metrics.items()}

            for row in data:
                attr_id = row["attribute_id"]
                if attr_id not in attr_map:
                    continue

                metric_code = attr_map[attr_id]
                start_date: date = row["start_date"]
                end_date = start_date + timedelta(days=365)
                # The data from USDA open API is the latest revised value.
                # If we map it to end_date + lag, we leak future restatements into the past.
                # To guarantee no look-ahead bias for backtests, we must treat this
                # freshly fetched historical revision as knowable only starting TODAY.
                release_date = date.today()

                payload = {
                    "commodity_code": spec.commodity_code,
                    "metric_code": metric_code,
                    "data_source_code": spec.source_code,
                    "market_year": row["market_year"],
                    "value": row["value"]
                }
                record = NormalizedRecord(
                    family=FactFamily.supply_demand_periodic,
                    data_source_code=spec.source_code,
                    commodity_code=spec.commodity_code,
                    metric_code=metric_code,
                    period_start=start_date,
                    period_end=end_date,
                    release_date=release_date,
                    value=row["value"],
                    unit="1000 bags", # typically 1000 60kg bags
                )

                key = f"{start_date.isoformat()}_{attr_id}"
                records.append(
                    attach_provenance(
                        record, payload, source_code=spec.source_code, origin=spec.usda_commodity_id, key=key
                    )
                )

        return records
