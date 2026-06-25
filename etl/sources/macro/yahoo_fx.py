"""Yahoo FX / dollar-index macro connector (feeds ``fact_macro_daily``).

Config-driven (``configs/ingestion/sources.yaml`` ``macro:``): each indicator maps
to a Yahoo ticker. Rows become ``NormalizedRecord``s with ``indicator_code`` and no
commodity (macro series are shared). Provenance is deterministic; the fetch function
is injectable so tests never hit the network. These series are collected for the
Drivers view — backtests show FX is not a robust forecast feature.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import MacroSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource

#: fetch(ticker, period) -> [{"date": date, "close": float}, ...]
MacroFetch = Callable[[str, str], list[dict[str, Any]]]


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


class MacroFxSource(BaseSource):
    family = FactFamily.macro_daily

    def __init__(self, specs: list[MacroSpec], *, period: str = "5d", fetch: MacroFetch | None = None) -> None:
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
                    "indicator_code": spec.indicator_code,
                    "data_source_code": spec.source_code,
                    "ticker": spec.ticker,
                    "observation_date": obs.isoformat(),
                    "value": row["close"],
                }
                record = NormalizedRecord(
                    family=FactFamily.macro_daily,
                    data_source_code=spec.source_code,
                    indicator_code=spec.indicator_code,
                    observation_date=obs,
                    release_date=obs + timedelta(days=spec.release_lag_days),
                    value=row["close"],
                    unit=spec.unit,
                )
                records.append(
                    attach_provenance(
                        record, payload, source_code=spec.source_code, origin=spec.ticker, key=obs.isoformat()
                    )
                )
        return records
