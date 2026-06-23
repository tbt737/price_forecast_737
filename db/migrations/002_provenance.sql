-- ============================================================================
-- 002_provenance.sql  —  Multi-Commodity Quant Forecasting Platform (Phase 4B)
-- ----------------------------------------------------------------------------
-- Additive source-provenance columns on every fact table. Mirrors the Alembic
-- migration apps/api/app/migrations/versions/0002_add_source_provenance_columns.py.
--
-- NULLABLE / optional (required provenance is Phase 4C). Idempotent
-- (ADD COLUMN IF NOT EXISTS); NO DROP; does NOT touch unique grain indexes or
-- existing data. Apply AFTER 001_core_schema.sql.
-- ============================================================================

ALTER TABLE fact_price_daily            ADD COLUMN IF NOT EXISTS source_record_id   VARCHAR(200);
ALTER TABLE fact_price_daily            ADD COLUMN IF NOT EXISTS source_payload_hash VARCHAR(64);
ALTER TABLE fact_weather_daily          ADD COLUMN IF NOT EXISTS source_record_id   VARCHAR(200);
ALTER TABLE fact_weather_daily          ADD COLUMN IF NOT EXISTS source_payload_hash VARCHAR(64);
ALTER TABLE fact_macro_daily            ADD COLUMN IF NOT EXISTS source_record_id   VARCHAR(200);
ALTER TABLE fact_macro_daily            ADD COLUMN IF NOT EXISTS source_payload_hash VARCHAR(64);
ALTER TABLE fact_logistics_periodic     ADD COLUMN IF NOT EXISTS source_record_id   VARCHAR(200);
ALTER TABLE fact_logistics_periodic     ADD COLUMN IF NOT EXISTS source_payload_hash VARCHAR(64);
ALTER TABLE fact_supply_demand_periodic ADD COLUMN IF NOT EXISTS source_record_id   VARCHAR(200);
ALTER TABLE fact_supply_demand_periodic ADD COLUMN IF NOT EXISTS source_payload_hash VARCHAR(64);
ALTER TABLE fact_event_risk             ADD COLUMN IF NOT EXISTS source_record_id   VARCHAR(200);
ALTER TABLE fact_event_risk             ADD COLUMN IF NOT EXISTS source_payload_hash VARCHAR(64);
