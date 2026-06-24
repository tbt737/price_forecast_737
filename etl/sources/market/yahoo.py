"""Yahoo Finance daily price connector (feeds ``fact_price_daily``).

Config-driven (``configs/ingestion/sources.yaml``): each instrument maps to a Yahoo
ticker. Rows become ``NormalizedRecord``s with deterministic provenance; the fetch
function is injectable so tests never touch the network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import PriceSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource

#: fetch(ticker, period) -> [{"date": date, "close": float}, ...]
PriceFetch = Callable[[str, str], list[dict[str, Any]]]


def _yfinance_fetch(ticker: str, period: str) -> list[dict[str, Any]]:
    import yfinance as yf

    frame = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        close = row.get("Close")
        if close is None or close != close:  # skip NaN
            continue
        rows.append({"date": index.date(), "close": round(float(close), 6)})
    return rows


class YahooPriceSource(BaseSource):
    family = FactFamily.price_daily

    def __init__(self, specs: list[PriceSpec], *, period: str = "5d", fetch: PriceFetch | None = None) -> None:
        self._specs = specs
        self._period = period
        self._fetch = fetch or _yfinance_fetch
        self.source_code = specs[0].source_code if specs else "yahoo"

    def collect(self) -> Iterable[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        for spec in self._specs:
            for row in self._fetch(spec.ticker, self._period):
                obs: date = row["date"]
                payload = {
                    "commodity_code": spec.commodity_code,
                    "instrument_code": spec.instrument_code,
                    "data_source_code": spec.source_code,
                    "ticker": spec.ticker,
                    "observation_date": obs.isoformat(),
                    "value": row["close"],
                    "currency": spec.currency,
                }
                record = NormalizedRecord(
                    family=FactFamily.price_daily,
                    data_source_code=spec.source_code,
                    commodity_code=spec.commodity_code,
                    instrument_code=spec.instrument_code,
                    observation_date=obs,
                    release_date=obs + timedelta(days=spec.release_lag_days),
                    value=row["close"],
                    currency=spec.currency,
                )
                records.append(
                    attach_provenance(
                        record, payload, source_code=spec.source_code, origin=spec.ticker, key=obs.isoformat()
                    )
                )
        return records
