"""ORM models — dimensions, region map, profile registry, and per-domain fact tables.

Importing this package registers every table on ``Base.metadata`` (used by both
the app and Alembic autogenerate).
"""

from app.models.dimensions import (
    CommodityGroup,
    CommodityProfileRegistry,
    CommodityRegionMap,
    DimCommodity,
    DimDataSource,
    DimMarketInstrument,
    DimRegion,
    RegionRole,
)
from app.models.facts import (
    FactEventRisk,
    FactLogisticsPeriodic,
    FactMacroDaily,
    FactPriceDaily,
    FactSupplyDemandPeriodic,
    FactWeatherDaily,
)

__all__ = [
    "CommodityGroup",
    "RegionRole",
    "DimCommodity",
    "DimRegion",
    "DimDataSource",
    "DimMarketInstrument",
    "CommodityRegionMap",
    "CommodityProfileRegistry",
    "FactPriceDaily",
    "FactWeatherDaily",
    "FactMacroDaily",
    "FactLogisticsPeriodic",
    "FactSupplyDemandPeriodic",
    "FactEventRisk",
]
