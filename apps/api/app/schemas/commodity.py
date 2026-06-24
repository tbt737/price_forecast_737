"""Pydantic response models for the read-only API."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict


class CommodityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    commodity_code: str
    commodity_name: str
    commodity_group: str
    base_unit: str
    default_currency: str
    notes: str | None = None


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_code: str
    exchange: str | None = None
    symbol: str | None = None
    contract_unit: str | None = None
    currency: str | None = None


class CommodityDetailOut(CommodityOut):
    instruments: list[InstrumentOut] = []


class ProfileRegistryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    commodity_code: str
    version: int
    checksum: str | None = None
    source_path: str | None = None


class ProfileDetailOut(ProfileRegistryOut):
    profile: dict[str, Any]


class PricePoint(BaseModel):
    date: date
    value: float


class PriceSeriesOut(BaseModel):
    """Daily price history for a commodity's benchmark instrument."""

    commodity_code: str
    instrument_code: str | None = None
    currency: str | None = None
    points: list[PricePoint] = []


class StatsOut(BaseModel):
    """Read-only dashboard summary counts."""

    commodities: int
    profiles: int
    instruments: int
    regions: int
    data_sources: int
    fact_rows: int


class HealthOut(BaseModel):
    status: str
    version: str


class ReadyOut(BaseModel):
    status: str
    database: str
