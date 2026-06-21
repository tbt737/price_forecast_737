"""FastAPI service for the Multi-Commodity Quant Forecasting Platform.

The ``app`` package owns the API service AND the persistence layer (ORM models,
Alembic migrations, and the idempotent commodity-profile loader). Everything is
generic and configuration-driven — no commodity is special-cased; all logic is
keyed on identifiers (commodity_code, region_code, instrument_code, source_code).
"""

__version__ = "0.2.0"
