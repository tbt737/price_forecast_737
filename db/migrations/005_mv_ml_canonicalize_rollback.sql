-- ============================================================================
-- 005_mv_ml_canonicalize_rollback.sql
-- REFERENCE — prefer: python scripts/canonicalize_ml_feature_mv.py --rollback
-- Restores the pre-cutover TABLE backup and removes the new matview.
-- Does not drop a leftover candidate; use --cleanup-candidate for that.
-- ============================================================================

BEGIN;
SELECT pg_advisory_xact_lock(hashtext('ml_feature_view_canonicalize'));
SET LOCAL lock_timeout = '3s';

DO $$
DECLARE
  mv_kind "char";
  bak_kind "char";
BEGIN
  SELECT c.relkind INTO mv_kind
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relname = 'mv_ml_daily_features_wide';

  SELECT c.relkind INTO bak_kind
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relname = 'mv_ml_daily_features_wide_table_bak';

  IF bak_kind IS DISTINCT FROM 'r' THEN
    RAISE EXCEPTION 'rollback: backup table mv_ml_daily_features_wide_table_bak missing or not a table';
  END IF;

  IF mv_kind = 'm' THEN
    EXECUTE 'DROP MATERIALIZED VIEW public.mv_ml_daily_features_wide';
  ELSIF mv_kind IS NOT NULL THEN
    RAISE EXCEPTION 'rollback: mv_ml_daily_features_wide exists with unexpected relkind=%', mv_kind;
  END IF;

  EXECUTE 'ALTER TABLE public.mv_ml_daily_features_wide_table_bak RENAME TO mv_ml_daily_features_wide';

  IF EXISTS (
    SELECT 1 FROM pg_class i
    JOIN pg_namespace n ON n.oid = i.relnamespace
    WHERE n.nspname = 'public' AND i.relname = 'uq_mv_ml_daily_features_wide_table_bak'
  ) THEN
    EXECUTE 'ALTER INDEX public.uq_mv_ml_daily_features_wide_table_bak RENAME TO uq_mv_ml_daily_features_wide';
  END IF;

  RAISE NOTICE 'rollback: restored TABLE mv_ml_daily_features_wide from backup';
END $$;

COMMIT;
