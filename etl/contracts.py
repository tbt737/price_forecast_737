"""Generic ETL contracts: fact families, their specs, and the normalized record.

No commodity is hard-coded. A normalized record carries business *codes*
(``commodity_code``, ``region_code``, ``instrument_code``, ``data_source_code``,
``metric_code``/``indicator_code``); surrogate-key resolution against the Phase 2
dimensions happens at real insert time (a later phase), not here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date
from typing import Any


class FactFamily(enum.StrEnum):
    """The six approved fact families (1:1 with the Phase 2 fact tables)."""

    price_daily = "price_daily"
    weather_daily = "weather_daily"
    macro_daily = "macro_daily"
    logistics_periodic = "logistics_periodic"
    supply_demand_periodic = "supply_demand_periodic"
    event_risk = "event_risk"


@dataclass(frozen=True)
class FamilySpec:
    """Static description of how a family maps to its approved fact table."""

    family: FactFamily
    target_table: str
    periodic: bool
    code_field: str  # the business code attribute: instrument_code | metric_code | indicator_code
    code_required: bool  # error if missing (price's instrument is only a warning)
    requires_commodity: bool  # commodity_key is NOT NULL on the target
    requires_region: bool  # region_key is NOT NULL on the target
    date_field: str | None  # target date column for daily/event facts (None for periodic)


# Source of truth for the ETL→schema contract. Mirrors apps/api/app/models/facts.py.
FACT_FAMILIES: dict[FactFamily, FamilySpec] = {
    FactFamily.price_daily: FamilySpec(
        FactFamily.price_daily, "fact_price_daily", False, "instrument_code", False, True, False, "price_date"
    ),
    FactFamily.weather_daily: FamilySpec(
        FactFamily.weather_daily, "fact_weather_daily", False, "metric_code", True, True, True, "weather_date"
    ),
    FactFamily.macro_daily: FamilySpec(
        FactFamily.macro_daily, "fact_macro_daily", False, "indicator_code", True, False, False, "macro_date"
    ),
    FactFamily.logistics_periodic: FamilySpec(
        FactFamily.logistics_periodic, "fact_logistics_periodic", True, "indicator_code", True, False, False, None
    ),
    FactFamily.supply_demand_periodic: FamilySpec(
        FactFamily.supply_demand_periodic, "fact_supply_demand_periodic", True, "metric_code", True, True, False, None
    ),
    FactFamily.event_risk: FamilySpec(
        FactFamily.event_risk, "fact_event_risk", False, "metric_code", True, False, False, "event_date"
    ),
}

# The only fact tables ETL may target. Any other target is UNKNOWN_TARGET_FACT.
APPROVED_FACT_TABLES: frozenset[str] = frozenset(spec.target_table for spec in FACT_FAMILIES.values())


@dataclass(frozen=True)
class NormalizedRecord:
    """A source-agnostic, point-in-time observation produced by an ETL source.

    ``data_source_code`` and ``release_date`` are universally required (source
    lineage + as-of date). ``observation_date`` is the date a daily/event value
    describes; periodic values use ``period_start``/``period_end`` instead.
    ``attributes`` carries family-specific extras (e.g. OHLC for price).
    """

    family: FactFamily
    data_source_code: str | None
    release_date: date | None
    commodity_code: str | None = None
    region_code: str | None = None
    instrument_code: str | None = None
    metric_code: str | None = None
    indicator_code: str | None = None
    observation_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    value: float | None = None
    unit: str | None = None
    currency: str | None = None
    revision: int = 0
    # Source provenance (Phase 4B) — optional; persisted but NOT part of the grain.
    source_record_id: str | None = None
    source_payload_hash: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    # input keys from_dict knows how to map (besides ``family``/``attributes``)
    _SCALAR_KEYS = frozenset(
        {
            "data_source_code", "commodity_code", "region_code", "instrument_code",
            "metric_code", "indicator_code", "value", "unit", "currency", "revision",
            "source_record_id", "source_payload_hash",
        }
    )
    _DATE_KEYS = frozenset({"release_date", "observation_date", "period_start", "period_end"})

    @classmethod
    def from_dict(cls, family: FactFamily, data: dict[str, Any]) -> NormalizedRecord:
        """Build a record from a fixture/plain dict (ISO date strings -> date).

        Safe & lossless: unknown input keys are NOT dropped silently — their names
        are recorded in ``attributes['_ignored_fields']`` (surfaced as an
        ``IGNORED_FIELD`` warning). A malformed date string is recorded in
        ``attributes['_parse_issues']`` (surfaced as an ``INVALID_DATE`` error) and
        the field is left None. No eval, no I/O.
        """
        kwargs: dict[str, Any] = {"family": family}
        attributes: dict[str, Any] = dict(data.get("attributes") or {})
        ignored: list[str] = []
        parse_issues: list[list[Any]] = []

        for key, raw in data.items():
            if key in ("family", "attributes"):
                continue
            if key in cls._DATE_KEYS:
                if raw is None:
                    kwargs[key] = None
                elif isinstance(raw, str):
                    try:
                        kwargs[key] = date.fromisoformat(raw)
                    except ValueError:
                        parse_issues.append([key, raw])
                        kwargs[key] = None
                else:
                    parse_issues.append([key, raw])
                    kwargs[key] = None
            elif key in cls._SCALAR_KEYS:
                kwargs[key] = raw
            else:
                ignored.append(key)

        # Required fields default to None when absent so a record can still be
        # constructed and then flagged by validation (e.g. MISSING_RELEASE_DATE).
        kwargs.setdefault("data_source_code", None)
        kwargs.setdefault("release_date", None)

        if ignored:
            attributes["_ignored_fields"] = ignored
        if parse_issues:
            attributes["_parse_issues"] = parse_issues
        return cls(**kwargs, attributes=attributes)

    def spec(self) -> FamilySpec | None:
        return FACT_FAMILIES.get(self.family)

    def code(self) -> str | None:
        """The business code for this family's ``code_field`` (or None)."""
        spec = self.spec()
        return getattr(self, spec.code_field, None) if spec else None

    def reference_date(self) -> date | None:
        """The date the value DESCRIBES — used for look-ahead checks."""
        spec = self.spec()
        if spec is None:
            return None
        return self.period_end if spec.periodic else self.observation_date
