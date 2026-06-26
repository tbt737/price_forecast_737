-- ============================================================================
-- 002_v_ml_daily_features_jsonb.sql
-- Phase 5A: Aggregated JSONB view for Machine Learning
-- ============================================================================

CREATE OR REPLACE VIEW v_ml_daily_features_jsonb AS
SELECT
    as_of_date,
    commodity_key,
    jsonb_agg(
        jsonb_build_object(
            'instrument_key', instrument_key,
            'region_key', region_key,
            'metric_code', metric_code,
            'metric_value_numeric', metric_value_numeric,
            'metric_value_text', metric_value_text,
            'source_table', source_table,
            'source_fact_id', source_fact_id,
            'observation_date', observation_date,
            'release_date', release_date,
            'data_source_key', data_source_key
        )
    ) AS features_jsonb
FROM v_ml_daily_feature_scalar
GROUP BY as_of_date, commodity_key;
