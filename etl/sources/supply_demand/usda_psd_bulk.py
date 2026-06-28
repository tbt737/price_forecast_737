"""USDA FAS PSD bulk supply & demand connector (feeds ``fact_supply_demand_periodic``).

Config-driven (``configs/ingestion/sources.yaml`` ``supply_demand:``).
Replaces the API-key-dependent version by downloading the public bulk CSV.
"""

from __future__ import annotations

import csv
import io
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from datetime import date, timedelta

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import SupplyDemandSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource


def _download_and_extract_csv() -> str:
    url = "https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"USDA PSD bulk download failed with HTTP {response.status}")
        zip_data = response.read()

    with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
        for name in z.namelist():
            if name.endswith(".csv"):
                return z.read(name).decode("utf-8")
    raise RuntimeError("USDA PSD bulk archive contained no CSV file")

class UsdaPsdBulkSource(BaseSource):
    family = FactFamily.supply_demand_periodic

    def __init__(self, specs: list[SupplyDemandSpec], *, fetch: Callable[[], str] | None = None) -> None:
        self._specs = specs
        self._fetch = fetch or _download_and_extract_csv
        self.source_code = specs[0].source_code if specs else "USDA_FAS"

    def collect(self) -> Iterable[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        if not self._specs:
            return records

        # Pre-build filtering dictionaries
        # commodity_map: {usda_commodity_id: {attribute_id: metric_code}}
        commodity_map: dict[str, dict[int, tuple[str, str]]] = {}
        for spec in self._specs:
            attr_map: dict[int, tuple[str, str]] = {}
            for metric_code, attr_id in spec.metrics.items():
                attr_map[attr_id] = (spec.commodity_code, metric_code)
            commodity_map[spec.usda_commodity_id] = attr_map

        csv_content = self._fetch()
        if not csv_content.strip():
            raise RuntimeError("USDA PSD bulk CSV was empty")

        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            comm_code = row.get("Commodity_Code")
            if not comm_code or comm_code not in commodity_map:
                continue

            attr_id_str = row.get("Attribute_ID")
            if not attr_id_str:
                continue

            attr_id = int(attr_id_str)
            if attr_id not in commodity_map[comm_code]:
                continue

            target_comm_code, metric_code = commodity_map[comm_code][attr_id]

            # The CSV has Market_Year, Month, Value
            try:
                market_year = int(row.get("Market_Year", 0))
                month = int(row.get("Month", 1))
                val = float(row.get("Value", 0.0))
            except ValueError:
                continue

            if market_year <= 0:
                continue

            # Fallback for month = 0, we can use 1 (January)
            if month == 0:
                month = 1

            try:
                start_date = date(market_year, month, 1)
            except ValueError:
                continue

            end_date = start_date + timedelta(days=365)

            # No look-ahead bias: set release date to today because this bulk file
            # contains fully revised historical values.
            release_date = date.today()

            payload = {
                "commodity_code": target_comm_code,
                "metric_code": metric_code,
                "data_source_code": self.source_code,
                "market_year": market_year,
                "value": val
            }
            record = NormalizedRecord(
                family=FactFamily.supply_demand_periodic,
                data_source_code=self.source_code,
                commodity_code=target_comm_code,
                metric_code=metric_code,
                period_start=start_date,
                period_end=end_date,
                release_date=release_date,
                value=val,
                unit=row.get("Unit_Description", "1000 MT"),
            )

            key = f"{start_date.isoformat()}_{attr_id}"
            records.append(
                attach_provenance(
                    record, payload, source_code=self.source_code, origin=comm_code, key=key
                )
            )

        if not records:
            raise RuntimeError("USDA PSD bulk CSV contained no rows matching configured commodities/metrics")
        return records
