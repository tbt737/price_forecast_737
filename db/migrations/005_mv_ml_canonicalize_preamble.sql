-- ============================================================================
-- 005_mv_ml_canonicalize_preamble.sql
-- REFERENCE / manual fragment ONLY — NOT the production apply path.
--
-- Production apply MUST use:
--   python scripts/canonicalize_ml_feature_mv.py --write
-- which holds pg_advisory_lock (SESSION) + a single transaction across
-- rename → CREATE MV → unique index → initial REFRESH → REVOKE.
--
-- Why this file alone is insufficient:
--   pg_advisory_xact_lock here is released at COMMIT of THIS file. Running
--   010/011/REFRESH in separate psql invocations drops the lock between steps.
--   CREATE MATERIALIZED VIEW IF NOT EXISTS also no-ops when a TABLE owns the name.
--
-- Rollback reference: 005_mv_ml_canonicalize_rollback.sql (relkind-checked).
-- Full sequence + parity: docs/ml/feature_view_refresh_runbook.md
-- ============================================================================

BEGIN;

-- Transaction-scoped lock — useful only if the remainder of the chain is in THIS
-- same transaction. Prefer the Python runner's session lock instead.
SELECT pg_advisory_xact_lock(hashtext('ml_feature_view_canonicalize'));

DO $$
DECLARE
  relkind "char";
  bak_name text := 'mv_ml_daily_features_wide_table_bak';
  bak_idx  text := 'uq_mv_ml_daily_features_wide_table_bak';
BEGIN
  SELECT c.relkind INTO relkind
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relname = 'mv_ml_daily_features_wide';

  IF relkind IS NULL THEN
    RAISE NOTICE 'preamble: public.mv_ml_daily_features_wide missing — nothing to rename';
    RETURN;
  END IF;

  IF relkind = 'm' THEN
    RAISE NOTICE 'preamble: already a materialized view — no rename; abort if you expected a table';
    RETURN;
  END IF;

  IF relkind <> 'r' THEN
    RAISE EXCEPTION 'preamble: unexpected relkind=% for mv_ml_daily_features_wide', relkind;
  END IF;

  -- Free the production name by renaming the TABLE (NOT DROP).
  IF to_regclass('public.' || bak_name) IS NOT NULL THEN
    RAISE EXCEPTION 'preamble: backup % already exists — resolve manually before retry', bak_name;
  END IF;

  EXECUTE format('ALTER TABLE public.mv_ml_daily_features_wide RENAME TO %I', bak_name);

  -- Unique index name does not follow table rename.
  IF to_regclass('public.uq_mv_ml_daily_features_wide') IS NOT NULL
     OR EXISTS (
          SELECT 1 FROM pg_class i
          JOIN pg_namespace n ON n.oid = i.relnamespace
          WHERE n.nspname = 'public' AND i.relname = 'uq_mv_ml_daily_features_wide'
        ) THEN
    EXECUTE format(
      'ALTER INDEX IF EXISTS public.uq_mv_ml_daily_features_wide RENAME TO %I',
      bak_idx
    );
  END IF;

  RAISE NOTICE 'preamble: renamed TABLE → % (index → %)', bak_name, bak_idx;
END $$;

COMMIT;

-- ---------------------------------------------------------------------------
-- NEXT (operator, still under approval) — NOT executed by this file:
--
--   SELECT to_regclass('public.mv_ml_daily_features_wide');  -- expect NULL
--   \i db/views/generated/010_mv_ml_daily_features_wide.sql
--   \i db/views/011_indexes_ml_feature_views.sql
--   REFRESH MATERIALIZED VIEW mv_ml_daily_features_wide;     -- initial, blocking
--   REVOKE ALL ON TABLE mv_ml_daily_features_wide FROM PUBLIC;
--   REVOKE ALL ON TABLE mv_ml_daily_features_wide FROM anon;
--   REVOKE ALL ON TABLE mv_ml_daily_features_wide FROM authenticated;
--   -- optional PG15+: ALTER MATERIALIZED VIEW ... ENABLE ROW LEVEL SECURITY;
--
-- Parity gates before flipping consumers: see runbook §Parity criteria.
-- ---------------------------------------------------------------------------
