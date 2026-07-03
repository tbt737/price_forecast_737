-- 004_rls_lockdown.sql — deny-by-default lockdown of the Supabase Data API (Phase SEC-1A).
--
-- WHY: the application (API / ETL / CI) talks to Postgres ONLY via DATABASE_URL as the
-- table-owner role; nothing in this repo uses the Supabase Data API (PostgREST) or the
-- anon key (verified: no supabase-js / supabase-py / createClient / anon key anywhere).
-- Supabase's defaults, however, grant table privileges in schema public to the `anon`
-- and `authenticated` roles — so anyone holding the public anon key could read AND WRITE
-- application tables (e.g. poison fact_price_daily, corrupting every forecast served).
--
-- WHAT (all idempotent, additive, zero data change):
--   1) enable ROW LEVEL SECURITY on every public base/partitioned table OWNED BY the
--      applying role (non-owned tables are skipped with a NOTICE instead of aborting the
--      block). With NO policies this is deny-by-default for non-owner roles. Deliberately
--      NOT `FORCE ROW LEVEL SECURITY`: the owner role used by DATABASE_URL must keep
--      bypassing RLS, so the backend/ETL are untouched.
--   2) revoke all table/sequence/function privileges from `anon` and `authenticated`,
--      and revoke the same via DEFAULT PRIVILEGES so FUTURE objects created by this role
--      don't silently re-open the hole. Guarded on role existence — the file still runs
--      on plain Postgres (docker-compose) where those Supabase roles don't exist.
--      `service_role` is intentionally untouched.
--   3) revoke everything from the PUBLIC pseudo-role (tables/sequences/functions +
--      default privileges), since anon/authenticated INHERIT PUBLIC grants — a
--      REVOKE FROM anon/authenticated alone leaves PUBLIC-granted access (notably the
--      default EXECUTE on future functions) wide open to PostgREST /rpc/.
--
-- APPLY PRECONDITION (SEC-1B): run this AS the DATABASE_URL / table-owner role (on
-- Supabase that is `postgres`, the same role whose default ACLs carry the anon grants).
-- ALTER DEFAULT PRIVILEGES only edits the executing role's default ACLs — applying as a
-- different admin role would silently skip the future-objects protection.
--
-- APPLY NOTE: this file is exactly THREE top-level statements (three DO blocks). Do NOT
-- split it on ';' (the ACC-1B harness lesson — semicolons exist INSIDE the blocks);
-- execute each DO block as one statement, or run the file via psql. Each ENABLE takes a
-- brief ACCESS EXCLUSIVE lock per table — prefer a low-traffic moment.

DO $$
DECLARE t record;
BEGIN
  FOR t IN
    SELECT c.relname, pg_get_userbyid(c.relowner) AS owner
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
  LOOP
    IF t.owner = current_user THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.relname);
    ELSE
      RAISE NOTICE 'skipping %.% (owned by %, not %)', 'public', t.relname, t.owner, current_user;
    END IF;
  END LOOP;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM authenticated;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM authenticated;
  END IF;
END $$;

-- Block 3: strip the PUBLIC pseudo-role. CRITICAL — `REVOKE ... FROM anon/authenticated`
-- does NOT remove privileges those roles inherit via PUBLIC, and Postgres grants EXECUTE
-- on every new function to PUBLIC by DEFAULT (the main future-RPC / PostgREST-rpc exposure).
-- PUBLIC always exists (no role guard needed). The table/function OWNER keeps all access
-- via ownership — revoking from PUBLIC never affects the DATABASE_URL owner role.
DO $$
BEGIN
  REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
  REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
  REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
END $$;
