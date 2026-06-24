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
class IngestionConfig:
    prices: list[PriceSpec]
    weather: list[WeatherSpec]

    @property
    def source_codes(self) -> set[str]:
        return {s.source_code for s in self.prices} | {s.source_code for s in self.weather}


@dataclass(frozen=True)
class CsvImportSpec:
    name: str
    path: str
    commodity_code: str
    instrument_code: str
    currency: str
    source_code: str
    commodity_column: str
    commodity_filter: str
    value_column: str
    date_column: str
    date_format: str
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
            commodity_column=c["commodity_column"],
            commodity_filter=c["commodity_filter"],
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

    return IngestionConfig(prices=prices, weather=weather)
