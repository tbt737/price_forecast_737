"""Unique-grain conflict pre-checks for planned fact inserts.

For each fact family we know the approved unique grain (mirrors the COALESCE
unique indexes in apps/api/app/models/facts.py). A conflict pre-check queries the
target table for an existing row with the same grain. NULL-safe: a NULL key
matches an existing NULL (the same semantics as ``COALESCE(key, -1)`` in the
index). Read-only — issues no writes.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    FactEventRisk,
    FactLogisticsPeriodic,
    FactMacroDaily,
    FactPriceDaily,
    FactSupplyDemandPeriodic,
    FactWeatherDaily,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.resolution import ResolutionResult

# family -> ORM model for the target fact table
TARGET_MODELS: dict[FactFamily, type] = {
    FactFamily.price_daily: FactPriceDaily,
    FactFamily.weather_daily: FactWeatherDaily,
    FactFamily.macro_daily: FactMacroDaily,
    FactFamily.logistics_periodic: FactLogisticsPeriodic,
    FactFamily.supply_demand_periodic: FactSupplyDemandPeriodic,
    FactFamily.event_risk: FactEventRisk,
}

# family -> ordered unique-grain column names (must mirror the unique indexes)
GRAIN_FIELDS: dict[FactFamily, tuple[str, ...]] = {
    FactFamily.price_daily: ("commodity_key", "market_instrument_key", "price_date", "revision"),
    FactFamily.weather_daily: ("commodity_key", "region_key", "metric_code", "weather_date", "revision"),
    FactFamily.macro_daily: ("commodity_key", "indicator_code", "macro_date", "revision"),
    FactFamily.logistics_periodic: (
        "commodity_key", "region_key", "data_source_key", "indicator_code",
        "period_start", "period_end", "release_date", "revision",
    ),
    FactFamily.supply_demand_periodic: (
        "commodity_key", "region_key", "data_source_key", "metric_code",
        "period_start", "period_end", "release_date", "revision",
    ),
    FactFamily.event_risk: ("commodity_key", "region_key", "metric_code", "event_date", "revision"),
}


def grain_values(record: NormalizedRecord, resolution: ResolutionResult) -> dict[str, Any]:
    """Build {grain_column: value} for the record's family from resolved keys + record."""
    spec = record.spec()
    if spec is None:
        return {}
    keys = resolution.resolved_keys()
    daily_date = record.observation_date
    available: dict[str, Any] = {
        "commodity_key": keys["commodity_key"],
        "region_key": keys["region_key"],
        "market_instrument_key": keys["market_instrument_key"],
        "data_source_key": keys["data_source_key"],
        "metric_code": record.metric_code,
        "indicator_code": record.indicator_code,
        "price_date": daily_date,
        "weather_date": daily_date,
        "macro_date": daily_date,
        "event_date": daily_date,
        "period_start": record.period_start,
        "period_end": record.period_end,
        "release_date": record.release_date,
        "revision": record.revision,
    }
    return {col: available[col] for col in GRAIN_FIELDS[record.family]}


def conflict_exists(session: Session, family: FactFamily, grain: dict[str, Any]) -> bool:
    """Return True if a row with this exact grain already exists in the target table.

    NULL-safe equality: a None value matches an existing NULL.
    """
    model = TARGET_MODELS[family]
    conditions = [
        getattr(model, col).is_(None) if value is None else getattr(model, col) == value
        for col, value in grain.items()
    ]
    return session.execute(select(model).where(*conditions).limit(1)).first() is not None
