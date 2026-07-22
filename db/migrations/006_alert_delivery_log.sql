-- ============================================================================
-- 006_alert_delivery_log.sql — weekly-alert delivery/idempotency record
-- ============================================================================
-- Operational table for the notification layer ONLY: it never touches market
-- data (dim_*/fact_* stay read-only for the alert script). One row per
-- (bulletin period, channel, masked destination). Statuses:
--   pending   — claimed before the send (claim-first: a rerun can never
--               double-send while a send is in flight or crashed)
--   delivered — provider accepted the message
--   failed    — provider rejected; a rerun MAY retry this channel
-- The alert script also runs this exact DDL via CREATE TABLE IF NOT EXISTS
-- (idempotent self-provisioning), so applying this migration is optional but
-- keeps the schema source-controlled and reviewable.
-- destination_fp is a truncated SHA-256 of the destination (chat id / email) —
-- never the raw destination, so the table leaks nothing if dumped.

-- Un-stick procedure (crashed in-flight send left status='pending'):
-- ⚠ MANDATORY: VERIFY THE REAL CHANNEL FIRST (open the Telegram chat / recipient
-- mailbox and check whether that period's bulletin actually arrived). Only then:
--   UPDATE alert_delivery_log SET status='delivered' ...  (it arrived), or
--   UPDATE alert_delivery_log SET status='failed'    ...  (confirmed absent ⇒ re-arm).
-- NEVER re-arm blindly — a blind pending→failed flip converts the fail-closed skip
-- into a possible duplicate send. The script itself never guesses on 'pending'.
-- Full runbook: docs/alerts/weekly-movers-runbook.md

CREATE TABLE IF NOT EXISTS alert_delivery_log (
    period_key     VARCHAR(80)  NOT NULL,
    channel        VARCHAR(20)  NOT NULL,
    destination_fp VARCHAR(16)  NOT NULL,
    status         VARCHAR(12)  NOT NULL,
    detail         VARCHAR(200),
    created_at     TIMESTAMP    NOT NULL,
    updated_at     TIMESTAMP    NOT NULL,
    PRIMARY KEY (period_key, channel, destination_fp)
);

-- Repo invariant since 004: every public table is deny-by-default RLS. The alert
-- writer connects as the table owner (service role), which bypasses RLS, so this
-- costs nothing operationally. (The script's portable CREATE TABLE IF NOT EXISTS
-- cannot include this — apply THIS migration on production.)
ALTER TABLE alert_delivery_log ENABLE ROW LEVEL SECURITY;
