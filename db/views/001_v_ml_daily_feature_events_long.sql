-- ============================================================================
-- 001_v_ml_daily_feature_events_long.sql
-- Phase 5A: Canonical Point-in-Time Long View
-- ============================================================================

-- 1. Lưới thời gian (Time Grid) theo coverage window của từng commodity
CREATE OR REPLACE VIEW v_ml_time_grid AS
WITH commodity_start_dates AS (
    SELECT
        c.commodity_key,
        (r.profile -> 'features' ->> 'min_train_start_date')::date AS profile_start_date,
        MIN(p.price_date) AS min_price_date
    FROM dim_commodity c
    LEFT JOIN commodity_profile_registry r ON c.commodity_key = r.commodity_key
    LEFT JOIN fact_price_daily p ON c.commodity_key = p.commodity_key
    GROUP BY c.commodity_key, r.profile
)
SELECT
    cs.commodity_key,
    g.as_of_date::date
FROM commodity_start_dates cs
JOIN LATERAL generate_series(
    COALESCE(cs.profile_start_date, cs.min_price_date, '2000-01-01'::date),
    CURRENT_DATE,
    '1 day'::interval
) g(as_of_date) ON true;

-- 2. View hợp nhất dạng Long (Point-in-Time Events)
CREATE OR REPLACE VIEW v_ml_daily_feature_events_long AS

SELECT * FROM (
  SELECT DISTINCT ON (g.commodity_key, g.as_of_date, p.market_instrument_key)
      g.as_of_date,
      g.commodity_key,
      p.market_instrument_key AS instrument_key,
      NULL::integer AS region_key,
      'price_close' AS metric_code,
      COALESCE(p.close, p.settle, p.value) AS metric_value_numeric,
      NULL::text AS metric_value_text,
      'fact_price_daily' AS source_table,
      p.price_id AS source_fact_id,
      p.price_date AS observation_date,
      p.release_date,
      p.data_source_key
  FROM v_ml_time_grid g
  JOIN fact_price_daily p
    ON p.commodity_key = g.commodity_key
    AND p.price_date <= g.as_of_date
    AND p.release_date <= g.as_of_date
  ORDER BY g.commodity_key, g.as_of_date, p.market_instrument_key, p.price_date DESC, p.release_date DESC, p.revision DESC
) price_events

UNION ALL

SELECT * FROM (
  SELECT DISTINCT ON (g.commodity_key, g.as_of_date, w.region_key, w.metric_code)
      g.as_of_date,
      g.commodity_key,
      NULL::integer AS instrument_key,
      w.region_key,
      w.metric_code,
      w.value AS metric_value_numeric,
      NULL::text AS metric_value_text,
      'fact_weather_daily' AS source_table,
      w.weather_id AS source_fact_id,
      w.weather_date AS observation_date,
      w.release_date,
      w.data_source_key
  FROM v_ml_time_grid g
  JOIN fact_weather_daily w
    ON w.commodity_key = g.commodity_key
    AND w.weather_date <= g.as_of_date
    AND w.release_date <= g.as_of_date
  ORDER BY g.commodity_key, g.as_of_date, w.region_key, w.metric_code, w.weather_date DESC, w.release_date DESC, w.revision DESC
) weather_events

UNION ALL

SELECT * FROM (
  SELECT DISTINCT ON (g.commodity_key, g.as_of_date, m.indicator_code)
      g.as_of_date,
      g.commodity_key,
      NULL::integer AS instrument_key,
      NULL::integer AS region_key,
      m.indicator_code AS metric_code,
      m.value AS metric_value_numeric,
      NULL::text AS metric_value_text,
      'fact_macro_daily' AS source_table,
      m.macro_id AS source_fact_id,
      m.macro_date AS observation_date,
      m.release_date,
      m.data_source_key
  FROM v_ml_time_grid g
  JOIN fact_macro_daily m
    ON (m.commodity_key = g.commodity_key OR m.commodity_key IS NULL)
    AND m.macro_date <= g.as_of_date
    AND m.release_date <= g.as_of_date
  ORDER BY g.commodity_key, g.as_of_date, m.indicator_code, m.macro_date DESC, m.release_date DESC, m.revision DESC
) macro_events

UNION ALL

SELECT * FROM (
  SELECT DISTINCT ON (g.commodity_key, g.as_of_date, l.region_key, l.indicator_code)
      g.as_of_date,
      g.commodity_key,
      NULL::integer AS instrument_key,
      l.region_key,
      l.indicator_code AS metric_code,
      l.value AS metric_value_numeric,
      NULL::text AS metric_value_text,
      'fact_logistics_periodic' AS source_table,
      l.logistics_id AS source_fact_id,
      l.period_end AS observation_date,
      l.release_date,
      l.data_source_key
  FROM v_ml_time_grid g
  JOIN fact_logistics_periodic l
    ON (l.commodity_key = g.commodity_key OR l.commodity_key IS NULL)
    AND l.period_end <= g.as_of_date
    AND l.release_date <= g.as_of_date
  ORDER BY g.commodity_key, g.as_of_date, l.region_key, l.indicator_code, l.period_end DESC, l.release_date DESC, l.revision DESC
) logistics_events

UNION ALL

SELECT * FROM (
  SELECT DISTINCT ON (g.commodity_key, g.as_of_date, sd.region_key, sd.metric_code)
      g.as_of_date,
      g.commodity_key,
      NULL::integer AS instrument_key,
      sd.region_key,
      sd.metric_code,
      sd.value AS metric_value_numeric,
      NULL::text AS metric_value_text,
      'fact_supply_demand_periodic' AS source_table,
      sd.sd_id AS source_fact_id,
      sd.period_end AS observation_date,
      sd.release_date,
      sd.data_source_key
  FROM v_ml_time_grid g
  JOIN fact_supply_demand_periodic sd
    ON sd.commodity_key = g.commodity_key
    AND sd.period_end <= g.as_of_date
    AND sd.release_date <= g.as_of_date
  ORDER BY g.commodity_key, g.as_of_date, sd.region_key, sd.metric_code, sd.period_end DESC, sd.release_date DESC, sd.revision DESC
) sd_events

UNION ALL

SELECT * FROM (
  SELECT DISTINCT ON (g.commodity_key, g.as_of_date, er.region_key, er.metric_code)
      g.as_of_date,
      g.commodity_key,
      NULL::integer AS instrument_key,
      er.region_key,
      er.metric_code,
      er.value AS metric_value_numeric,
      er.category AS metric_value_text,
      'fact_event_risk' AS source_table,
      er.event_id AS source_fact_id,
      er.event_date AS observation_date,
      er.release_date,
      er.data_source_key
  FROM v_ml_time_grid g
  JOIN fact_event_risk er
    ON (er.commodity_key = g.commodity_key OR er.commodity_key IS NULL)
    AND er.event_date <= g.as_of_date
    AND er.release_date <= g.as_of_date
  ORDER BY g.commodity_key, g.as_of_date, er.region_key, er.metric_code, er.event_date DESC, er.release_date DESC, er.revision DESC
) er_events;

-- 3. Scalar collapse for wide-panel grain (one value per metric per day/commodity)
-- Tie-break when region/instrument differ: global (NULL) first, then lowest key,
-- then freshest observation/release, then highest source_fact_id.
CREATE OR REPLACE VIEW v_ml_daily_feature_scalar AS
SELECT DISTINCT ON (as_of_date, commodity_key, metric_code)
    as_of_date,
    commodity_key,
    instrument_key,
    region_key,
    metric_code,
    metric_value_numeric,
    metric_value_text,
    source_table,
    source_fact_id,
    observation_date,
    release_date,
    data_source_key
FROM v_ml_daily_feature_events_long
ORDER BY
    as_of_date,
    commodity_key,
    metric_code,
    region_key NULLS FIRST,
    instrument_key NULLS FIRST,
    observation_date DESC,
    release_date DESC,
    source_fact_id DESC;
