"""Per-domain fact tables.

Approved physical table names: fact_price_daily, fact_weather_daily,
fact_macro_daily, fact_logistics_periodic, fact_supply_demand_periodic,
fact_event_risk.

Every fact table is point-in-time correct:
  * an observation/period/event date (the date the value DESCRIBES), and
  * ``release_date`` (when the value first became KNOWABLE), guarded by
    ``CHECK (release_date >= <date>)``.
Revisions are append-only via ``revision`` (a revised series gets a new row,
never an UPDATE), so a backtest can reconstruct "what was known at time T".

NULL-safe grain uniqueness is enforced by COALESCE unique indexes (bottom of
file): a plain UNIQUE would not dedupe rows whose nullable FKs are NULL. Each
fact also has a plain ``release_date`` index for point-in-time range scans.

Metric/indicator granularity is carried as ``*_code`` text columns (the
dimension set is commodity/region/source/instrument), keeping the schema
generic: a new metric is new rows, never a schema change.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class _FactMixin(TimestampMixin):
    """Shared point-in-time columns for every fact table."""

    release_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(20, 6))
    unit: Mapped[str | None] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FactPriceDaily(_FactMixin, Base):
    """Daily market prices/bars for a market instrument."""

    __tablename__ = "fact_price_daily"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_fact_price_daily_revision"),
        CheckConstraint("release_date >= price_date", name="ck_fact_price_daily_release"),
    )

    price_id: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE"), nullable=False
    )
    market_instrument_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_market_instrument.market_instrument_key", ondelete="SET NULL")
    )
    data_source_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_data_source.data_source_key", ondelete="SET NULL")
    )
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float | None] = mapped_column(Numeric(20, 6))
    high: Mapped[float | None] = mapped_column(Numeric(20, 6))
    low: Mapped[float | None] = mapped_column(Numeric(20, 6))
    close: Mapped[float | None] = mapped_column(Numeric(20, 6))
    settle: Mapped[float | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[float | None] = mapped_column(Numeric(20, 2))
    open_interest: Mapped[float | None] = mapped_column(Numeric(20, 2))
    currency: Mapped[str | None] = mapped_column(String(10))


class FactWeatherDaily(_FactMixin, Base):
    """Daily weather/agroclimatology observations for a (commodity, region)."""

    __tablename__ = "fact_weather_daily"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_fact_weather_daily_revision"),
        CheckConstraint("release_date >= weather_date", name="ck_fact_weather_daily_release"),
    )

    weather_id: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE"), nullable=False
    )
    region_key: Mapped[int] = mapped_column(
        ForeignKey("dim_region.region_key", ondelete="CASCADE"), nullable=False
    )
    data_source_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_data_source.data_source_key", ondelete="SET NULL")
    )
    weather_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(60), nullable=False)  # rainfall_mm, tmax_c, ...


class FactMacroDaily(_FactMixin, Base):
    """Daily macro/financial driver series. ``commodity_key`` nullable (shared indicators)."""

    __tablename__ = "fact_macro_daily"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_fact_macro_daily_revision"),
        CheckConstraint("release_date >= macro_date", name="ck_fact_macro_daily_release"),
    )

    macro_id: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE")
    )
    data_source_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_data_source.data_source_key", ondelete="SET NULL")
    )
    macro_date: Mapped[date] = mapped_column(Date, nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(80), nullable=False)  # usd_vnd, dxy, real_yields_10y


class FactLogisticsPeriodic(_FactMixin, Base):
    """Periodic logistics/freight indicators. ``commodity_key``/``region_key`` nullable (global)."""

    __tablename__ = "fact_logistics_periodic"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_fact_logistics_revision"),
        CheckConstraint("period_end >= period_start", name="ck_fact_logistics_period"),
        CheckConstraint("release_date >= period_end", name="ck_fact_logistics_release"),
    )

    logistics_id: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE")
    )
    region_key: Mapped[int | None] = mapped_column(ForeignKey("dim_region.region_key", ondelete="SET NULL"))
    data_source_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_data_source.data_source_key", ondelete="SET NULL")
    )
    # Explicit period range (start..end), not a single reference date — removes
    # ambiguity for weekly/monthly/quarterly/marketing-year logistics series.
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(80), nullable=False)  # BDI, FBX, port_congestion


class FactSupplyDemandPeriodic(_FactMixin, Base):
    """Periodic supply & demand fundamentals (production, stocks, exports, crush)."""

    __tablename__ = "fact_supply_demand_periodic"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_fact_sd_revision"),
        CheckConstraint("period_end >= period_start", name="ck_fact_sd_period"),
        CheckConstraint("release_date >= period_end", name="ck_fact_sd_release"),
    )

    sd_id: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE"), nullable=False
    )
    region_key: Mapped[int | None] = mapped_column(ForeignKey("dim_region.region_key", ondelete="SET NULL"))
    data_source_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_data_source.data_source_key", ondelete="SET NULL")
    )
    # Explicit period range (e.g. a marketing year / month / quarter window).
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(80), nullable=False)  # production_estimate, ending_stocks


class FactEventRisk(_FactMixin, Base):
    """Event-risk signals (weather shocks, geopolitics, policy/tariff, disease).

    ``commodity_key``/``region_key`` nullable: some risks are global (e.g. a
    chokepoint disruption). ``value`` carries a severity/probability/index; the
    risk type is the ``metric_code`` (e.g. el_nino_la_nina, eudr_compliance).
    """

    __tablename__ = "fact_event_risk"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_fact_event_risk_revision"),
        CheckConstraint("release_date >= event_date", name="ck_fact_event_risk_release"),
    )

    event_id: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE")
    )
    region_key: Mapped[int | None] = mapped_column(ForeignKey("dim_region.region_key", ondelete="SET NULL"))
    data_source_key: Mapped[int | None] = mapped_column(
        ForeignKey("dim_data_source.data_source_key", ondelete="SET NULL")
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(80), nullable=False)  # el_nino_la_nina, eudr_compliance
    category: Mapped[str | None] = mapped_column(String(40))  # weather|geopolitical|policy|disease


# ── NULL-safe grain uniqueness (COALESCE unique indexes) ──────────────────────
Index(
    "uq_fact_price_daily_grain",
    FactPriceDaily.commodity_key,
    func.coalesce(FactPriceDaily.market_instrument_key, -1),
    FactPriceDaily.price_date,
    FactPriceDaily.revision,
    unique=True,
)
Index(
    "uq_fact_weather_daily_grain",
    FactWeatherDaily.commodity_key,
    FactWeatherDaily.region_key,
    FactWeatherDaily.metric_code,
    FactWeatherDaily.weather_date,
    FactWeatherDaily.revision,
    unique=True,
)
Index(
    "uq_fact_macro_daily_grain",
    func.coalesce(FactMacroDaily.commodity_key, -1),
    FactMacroDaily.indicator_code,
    FactMacroDaily.macro_date,
    FactMacroDaily.revision,
    unique=True,
)
Index(
    "uq_fact_logistics_grain",
    func.coalesce(FactLogisticsPeriodic.commodity_key, -1),
    func.coalesce(FactLogisticsPeriodic.region_key, -1),
    FactLogisticsPeriodic.data_source_key,
    FactLogisticsPeriodic.indicator_code,
    FactLogisticsPeriodic.period_start,
    FactLogisticsPeriodic.period_end,
    FactLogisticsPeriodic.release_date,
    FactLogisticsPeriodic.revision,
    unique=True,
)
Index(
    "uq_fact_sd_grain",
    FactSupplyDemandPeriodic.commodity_key,
    func.coalesce(FactSupplyDemandPeriodic.region_key, -1),
    FactSupplyDemandPeriodic.data_source_key,
    FactSupplyDemandPeriodic.metric_code,
    FactSupplyDemandPeriodic.period_start,
    FactSupplyDemandPeriodic.period_end,
    FactSupplyDemandPeriodic.release_date,
    FactSupplyDemandPeriodic.revision,
    unique=True,
)
Index(
    "uq_fact_event_risk_grain",
    func.coalesce(FactEventRisk.commodity_key, -1),
    func.coalesce(FactEventRisk.region_key, -1),
    FactEventRisk.metric_code,
    FactEventRisk.event_date,
    FactEventRisk.revision,
    unique=True,
)

# ── release_date indexes for point-in-time range scans ────────────────────────
Index("ix_fact_price_daily_release_date", FactPriceDaily.release_date)
Index("ix_fact_weather_daily_release_date", FactWeatherDaily.release_date)
Index("ix_fact_macro_daily_release_date", FactMacroDaily.release_date)
Index("ix_fact_logistics_periodic_release_date", FactLogisticsPeriodic.release_date)
Index("ix_fact_supply_demand_periodic_release_date", FactSupplyDemandPeriodic.release_date)
Index("ix_fact_event_risk_release_date", FactEventRisk.release_date)
