"""Local CSV price connector — backfill from a downloaded dataset.

Reads a CSV (e.g. Kaggle Agmarknet mandi prices), filters to one commodity (and
optionally one market), collapses multiple rows per day to a single price
(``aggregate``), and emits ``fact_price_daily`` records with deterministic
provenance. Config-driven via ``configs/ingestion/csv_imports.yaml``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import CsvImportSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource


class CsvPriceSource(BaseSource):
    family = FactFamily.price_daily

    def __init__(self, spec: CsvImportSpec) -> None:
        self.spec = spec
        self.source_code = spec.source_code

    def collect(self) -> Iterable[NormalizedRecord]:
        import pandas as pd

        spec = self.spec
        usecols = [spec.commodity_column, spec.value_column, spec.date_column]
        if spec.market_column:
            usecols.append(spec.market_column)
        frame = pd.read_csv(spec.path, usecols=usecols, low_memory=False)

        frame = frame[frame[spec.commodity_column].astype(str) == spec.commodity_filter]
        if spec.market_column and spec.market_filter:
            mask = frame[spec.market_column].astype(str).str.contains(spec.market_filter, case=False, na=False)
            frame = frame[mask]

        days = pd.to_datetime(frame[spec.date_column], format=spec.date_format, errors="coerce")
        values = pd.to_numeric(frame[spec.value_column], errors="coerce")
        good = days.notna() & values.notna() & (values > 0)
        clean = pd.DataFrame({"d": days[good].dt.date, "v": values[good]})
        series = clean.groupby("d")["v"].agg(spec.aggregate)

        records: list[NormalizedRecord] = []
        for observed, value in series.items():
            obs: date = observed  # date object from .dt.date grouping
            price = round(float(value), 4)
            payload = {
                "commodity_code": spec.commodity_code,
                "instrument_code": spec.instrument_code,
                "data_source_code": spec.source_code,
                "observation_date": obs.isoformat(),
                "value": price,
                "currency": spec.currency,
            }
            record = NormalizedRecord(
                family=FactFamily.price_daily,
                data_source_code=spec.source_code,
                commodity_code=spec.commodity_code,
                instrument_code=spec.instrument_code,
                observation_date=obs,
                release_date=obs + timedelta(days=1),
                value=price,
                currency=spec.currency,
            )
            records.append(
                attach_provenance(
                    record, payload, source_code=spec.source_code, origin=spec.instrument_code, key=obs.isoformat()
                )
            )
        return records
