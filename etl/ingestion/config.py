"""Loader for the ingestion source registry (``configs/ingestion/sources.yaml``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "ingestion" / "sources.yaml"
CSV_IMPORTS_PATH = Path(__file__).resolve().parents[2] / "configs" / "ingestion" / "csv_imports.yaml"


@dataclass(frozen=True)
class PriceSpec:
    commodity_code: str
    instrument_code: str
    ticker: str
    currency: str
    source_code: str
    release_lag_days: int


@dataclass(frozen=True)
class WeatherSpec:
    commodity_code: str
    region_code: str
    latitude: float
    longitude: float
    source_code: str
    release_lag_days: int
    parameters: dict[str, str]  # NASA POWER api param -> metric_code


@dataclass(frozen=True)
class MacroSpec:
    indicator_code: str  # free-text on fact_macro_daily (e.g. "usd_inr")
    ticker: str
    source_code: str
    release_lag_days: int
    unit: str | None = None


@dataclass(frozen=True)
class EventRiskSpec:
    metric_code: str
    category: str
    source_code: str
    release_lag_days: int
    description: str | None = None

@dataclass(frozen=True)
class SupplyDemandSpec:
    commodity_code: str
    usda_commodity_id: str
    source_code: str
    release_lag_days: int
    metrics: dict[str, int] # metric_code -> usda attribute ID

@dataclass(frozen=True)
class IngestionConfig:
    prices: list[PriceSpec]
    weather: list[WeatherSpec]
    macro: list[MacroSpec]
    events: list[EventRiskSpec]
    supply_demand: list[SupplyDemandSpec]

    @property
    def source_codes(self) -> set[str]:
        return (
            {s.source_code for s in self.prices}
            | {s.source_code for s in self.weather}
            | {s.source_code for s in self.macro}
            | {s.source_code for s in self.events}
            | {s.source_code for s in self.supply_demand}
        )


@dataclass(frozen=True)
class CsvImportSpec:
    name: str
    path: str
    commodity_code: str
    instrument_code: str
    currency: str
    source_code: str
    value_column: str
    date_column: str
    date_format: str
    # Optional: filter rows to one commodity. Omit for single-commodity files.
    commodity_column: str | None = None
    commodity_filter: str | None = None
    aggregate: str = "median"
    market_column: str | None = None
    market_filter: str | None = None


def load_csv_imports(path: Path = CSV_IMPORTS_PATH) -> dict[str, CsvImportSpec]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, CsvImportSpec] = {}
    for name, c in (data.get("imports") or {}).items():
        out[name] = CsvImportSpec(
            name=name,
            path=c["path"],
            commodity_code=c["commodity_code"],
            instrument_code=c["instrument_code"],
            currency=c.get("currency", "USD"),
            source_code=c.get("source_code", "csv_import"),
            commodity_column=c.get("commodity_column"),
            commodity_filter=c.get("commodity_filter"),
            value_column=c["value_column"],
            date_column=c["date_column"],
            date_format=c["date_format"],
            aggregate=c.get("aggregate", "median"),
            market_column=c.get("market_column"),
            market_filter=c.get("market_filter"),
        )
    return out


def load_ingestion_config(path: Path = CONFIG_PATH) -> IngestionConfig:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    p = data.get("prices", {}) or {}
    p_source = p.get("source_code", "yahoo")
    p_lag = int(p.get("release_lag_days", 1))
    prices = [
        PriceSpec(
            commodity_code=i["commodity_code"],
            instrument_code=i["instrument_code"],
            ticker=i["ticker"],
            currency=i.get("currency", "USD"),
            source_code=p_source,
            release_lag_days=p_lag,
        )
        for i in p.get("instruments", [])
    ]

    w = data.get("weather", {}) or {}
    w_source = w.get("source_code", "NASA_POWER")
    w_lag = int(w.get("release_lag_days", 3))
    w_params = dict(w.get("parameters", {}))
    weather = [
        WeatherSpec(
            commodity_code=loc["commodity_code"],
            region_code=loc["region_code"],
            latitude=float(loc["latitude"]),
            longitude=float(loc["longitude"]),
            source_code=w_source,
            release_lag_days=w_lag,
            parameters=w_params,
        )
        for loc in w.get("locations", [])
    ]

    mc = data.get("macro", {}) or {}
    mc_source = mc.get("source_code", "yahoo")
    mc_lag = int(mc.get("release_lag_days", 1))
    macro = [
        MacroSpec(
            indicator_code=ind["indicator_code"],
            ticker=ind["ticker"],
            source_code=mc_source,
            release_lag_days=mc_lag,
            unit=ind.get("unit"),
        )
        for ind in mc.get("indicators", [])
    ]

    ev = data.get("events", {}) or {}
    ev_source = ev.get("source_code", "NOAA")
    ev_lag = int(ev.get("release_lag_days", 10))
    events = [
        EventRiskSpec(
            metric_code=m["metric_code"],
            category=m.get("category", "climate"),
            source_code=ev_source,
            release_lag_days=ev_lag,
            description=m.get("description"),
        )
        for m in ev.get("metrics", [])
    ]

    sd = data.get("supply_demand", {}) or {}
    sd_source = sd.get("source_code", "USDA_FAS")
    sd_lag = int(sd.get("release_lag_days", 0))
    supply_demand = [
        SupplyDemandSpec(
            commodity_code=s["commodity_code"],
            usda_commodity_id=s["usda_commodity_id"],
            source_code=sd_source,
            release_lag_days=sd_lag,
            metrics=s.get("metrics", {}),
        )
        for s in sd.get("series", [])
    ]

    return IngestionConfig(prices=prices, weather=weather, macro=macro, events=events, supply_demand=supply_demand)
