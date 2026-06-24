"""Loader for the ingestion source registry (``configs/ingestion/sources.yaml``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "ingestion" / "sources.yaml"


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
