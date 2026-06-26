-- ============================================================================
-- 011_indexes_ml_feature_views.sql
-- Phase 5C: Indexes cho Materialized View
-- ============================================================================

-- Bắt buộc phải có UNIQUE INDEX để PostgreSQL có thể thực hiện
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mà không block các câu query đang đọc.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_ml_daily_features_wide
ON mv_ml_daily_features_wide (commodity_key, as_of_date);