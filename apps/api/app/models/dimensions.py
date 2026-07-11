"""Dimension tables, the commodity↔region map, and the profile registry.

Approved physical table names:
  dim_commodity, dim_market_instrument, dim_region, commodity_region_map,
  dim_data_source, commodity_profile_registry.

Surrogate ``*_key`` primary keys; natural ``*_code`` business keys are UNIQUE.
Dimensions are global and deduplicated by code (a region/source shared by many
commodities is stored once). ``dim_market_instrument`` is scoped to a commodity
because the same instrument_code (e.g. CN_FOB_QINGDAO) denotes different goods
per commodity. Per-commodity region context (role/label) lives on
``commodity_region_map``.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.types import JSONColumn


class CommodityGroup(enum.StrEnum):
    agriculture = "agriculture"
    energy = "energy"
    metal = "metal"
    logistics = "logistics"
    equity = "equity"  # listed shares (e.g. Vietnamese VN30 blue chips) — same generic pipeline


class RegionRole(enum.StrEnum):
    production = "production"
    consumption = "consumption"
    export = "export"
    import_ = "import"
    weather = "weather"


_commodity_group = Enum(
    CommodityGroup, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]
)
_region_role = Enum(
    RegionRole, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]
)


class DimCommodity(TimestampMixin, Base):
    __tablename__ = "dim_commodity"

    commodity_key: Mapped[int] = mapped_column(primary_key=True)
    commodity_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    commodity_name: Mapped[str] = mapped_column(String(120), nullable=False)
    commodity_group: Mapped[CommodityGroup] = mapped_column(_commodity_group, nullable=False)
    base_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    default_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    instruments: Mapped[list[DimMarketInstrument]] = relationship(
        back_populates="commodity", cascade="all, delete-orphan"
    )
    region_map: Mapped[list[CommodityRegionMap]] = relationship(
        back_populates="commodity", cascade="all, delete-orphan"
    )
    profile_registry: Mapped[CommodityProfileRegistry | None] = relationship(
        back_populates="commodity", cascade="all, delete-orphan", uselist=False
    )


class DimRegion(TimestampMixin, Base):
    """Global geography dimension (production/consumption/export/import/weather areas)."""

    __tablename__ = "dim_region"

    region_key: Mapped[int] = mapped_column(primary_key=True)
    region_code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    region_name: Mapped[str] = mapped_column(String(160), nullable=False)
    country: Mapped[str | None] = mapped_column(String(60))


class DimDataSource(TimestampMixin, Base):
    """Global data-source / provenance dimension."""

    __tablename__ = "dim_data_source"

    data_source_key: Mapped[int] = mapped_column(primary_key=True)
    source_code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(300))
    access: Mapped[str | None] = mapped_column(String(40))
    license: Mapped[str | None] = mapped_column(String(120))


class DimMarketInstrument(TimestampMixin, Base):
    """Market/tradable series, scoped to a commodity."""

    __tablename__ = "dim_market_instrument"
    __table_args__ = (
        UniqueConstraint("commodity_key", "instrument_code", name="uq_dim_market_instrument_commodity_code"),
    )

    market_instrument_key: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE"), nullable=False
    )
    instrument_code: Mapped[str] = mapped_column(String(60), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(120))
    symbol: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    contract_unit: Mapped[str | None] = mapped_column(String(60))
    currency: Mapped[str | None] = mapped_column(String(10))

    commodity: Mapped[DimCommodity] = relationship(back_populates="instruments")


class CommodityRegionMap(TimestampMixin, Base):
    """Maps a commodity to a region with a role (production/consumption/.../weather).

    The same region may map to one commodity under several roles (e.g. China is
    both producer and consumer), so the grain is (commodity, region, role).
    """

    __tablename__ = "commodity_region_map"
    __table_args__ = (
        UniqueConstraint("commodity_key", "region_key", "role", name="uq_commodity_region_map"),
    )

    map_id: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE"), nullable=False
    )
    region_key: Mapped[int] = mapped_column(
        ForeignKey("dim_region.region_key", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[RegionRole] = mapped_column(_region_role, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))  # commodity-specific contextual name

    commodity: Mapped[DimCommodity] = relationship(back_populates="region_map")
    region: Mapped[DimRegion] = relationship()


class CommodityProfileRegistry(TimestampMixin, Base):
    """Registers each commodity's YAML profile (full JSON + checksum for idempotency)."""

    __tablename__ = "commodity_profile_registry"

    registry_id: Mapped[int] = mapped_column(primary_key=True)
    commodity_key: Mapped[int] = mapped_column(
        ForeignKey("dim_commodity.commodity_key", ondelete="CASCADE"), nullable=False, unique=True
    )
    commodity_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    source_path: Mapped[str | None] = mapped_column(String(300))
    checksum: Mapped[str | None] = mapped_column(String(64))  # sha256 hex of the profile file
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    profile: Mapped[dict] = mapped_column(JSONColumn, nullable=False)

    commodity: Mapped[DimCommodity] = relationship(back_populates="profile_registry")
