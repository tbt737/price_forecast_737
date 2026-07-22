-- ============================================================================
-- 007_weekly_alert_runner.sql — least-privilege execution identity for the
-- weekly movers bulletin (WEEKLY-MOVERS-1D). PostgreSQL-only; idempotent.
-- ============================================================================
-- Design (narrower of the two mandated options): the runner NEVER touches
-- alert_delivery_log directly — all writes go through three SECURITY DEFINER
-- functions with fixed search_path, status/channel validation and atomic CAS.
-- Structurally impossible for the runner: DELETE, PK edits, delivered→failed,
-- blind pending re-arm, invalid statuses, reading other tables.
-- The role's password is NEVER set here (no secrets in the repo):
--   ALTER ROLE weekly_alert_runner PASSWORD '...'  is run out-of-band.

-- 1) Role: login-only, no ownership, no DDL, no role/db creation, no RLS bypass.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'weekly_alert_runner') THEN
        CREATE ROLE weekly_alert_runner
            LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOBYPASSRLS NOREPLICATION CONNECTION LIMIT 3;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO weekly_alert_runner;

-- 2) Read allowlist (exact call graph of scripts/weekly_movers_alert.py):
--    dim_commodity, dim_market_instrument, fact_price_daily   (ranking + series)
--    mv_ml_daily_features_wide                                 (forecast exog)
GRANT SELECT ON public.dim_commodity, public.dim_market_instrument,
                public.fact_price_daily TO weekly_alert_runner;
GRANT SELECT ON public.mv_ml_daily_features_wide TO weekly_alert_runner;
-- NOTE: the production relation name is stable — the offline pandas builder
-- (ml/build_pandas_mv.py) hard-refuses to rename into this name, and
-- scripts/refresh_ml_features.py only REFRESHes in place — so this grant
-- survives; if a future migration ever recreates the relation, re-apply it.

-- RLS read policies (004 made every contract table deny-by-default; a plain GRANT
-- is not sufficient for a non-owner role):
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['dim_commodity','dim_market_instrument','fact_price_daily']
    LOOP
        IF NOT EXISTS (
            SELECT FROM pg_policies
            WHERE schemaname = 'public' AND tablename = t
              AND policyname = 'weekly_alert_read'
        ) THEN
            -- string concat + quote_ident (no '%' characters: some drivers'
            -- client-side parameter parsers choke on format()'s %I in DO blocks)
            EXECUTE 'CREATE POLICY weekly_alert_read ON public.' || quote_ident(t)
                 || ' FOR SELECT TO weekly_alert_runner USING (true)';
        END IF;
    END LOOP;
END $$;

-- 3) Delivery-log interface — SECURITY DEFINER, owner = migration runner
--    (postgres), fixed search_path, PUBLIC revoked, EXECUTE only for the runner.

-- claim: atomically either (a) CAS-re-arm a FAILED row, or (b) insert a fresh
-- pending claim; an existing delivered/pending row (or a lost insert race)
-- returns false. Never touches other statuses, keys or rows.
CREATE OR REPLACE FUNCTION public.alert_claim(
    p_key varchar, p_channel varchar, p_dest varchar
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF p_channel NOT IN ('telegram', 'email') THEN
        RAISE EXCEPTION 'invalid channel';
    END IF;
    UPDATE alert_delivery_log
       SET status = 'pending', updated_at = now()
     WHERE period_key = p_key AND channel = p_channel
       AND destination_fp = p_dest AND status = 'failed';
    IF FOUND THEN
        RETURN true;
    END IF;
    BEGIN
        INSERT INTO alert_delivery_log
            (period_key, channel, destination_fp, status, detail, created_at, updated_at)
        VALUES (p_key, p_channel, p_dest, 'pending', NULL, now(), now());
        RETURN true;
    EXCEPTION WHEN unique_violation THEN
        RETURN false;  -- delivered / in-flight / lost race ⇒ caller must not send
    END;
END $$;

-- mark: ONLY the pending→delivered|failed transitions exist. delivered rows are
-- immutable; pending can never be re-armed here; keys cannot be modified.
CREATE OR REPLACE FUNCTION public.alert_mark(
    p_key varchar, p_channel varchar, p_dest varchar,
    p_status varchar, p_detail varchar DEFAULT NULL
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF p_status NOT IN ('delivered', 'failed') THEN
        RAISE EXCEPTION 'invalid status';
    END IF;
    UPDATE alert_delivery_log
       SET status = p_status, detail = left(p_detail, 200), updated_at = now()
     WHERE period_key = p_key AND channel = p_channel
       AND destination_fp = p_dest AND status = 'pending';
    RETURN FOUND;
END $$;

-- status: read-back of one record's status (fingerprints only — the table never
-- stores a raw destination, so nothing sensitive can be returned).
CREATE OR REPLACE FUNCTION public.alert_status(
    p_key varchar, p_channel varchar, p_dest varchar
) RETURNS varchar
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT status FROM alert_delivery_log
    WHERE period_key = p_key AND channel = p_channel AND destination_fp = p_dest;
$$;

REVOKE ALL ON FUNCTION public.alert_claim(varchar, varchar, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.alert_mark(varchar, varchar, varchar, varchar, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.alert_status(varchar, varchar, varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.alert_claim(varchar, varchar, varchar) TO weekly_alert_runner;
GRANT EXECUTE ON FUNCTION public.alert_mark(varchar, varchar, varchar, varchar, varchar) TO weekly_alert_runner;
GRANT EXECUTE ON FUNCTION public.alert_status(varchar, varchar, varchar) TO weekly_alert_runner;
