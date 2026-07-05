# VN freshness monitor (ETL-VN-4)

A dedicated, **read-only** GitHub Actions workflow that catches a silently-dead Vietnam
domestic price scraper (GOLD_VN / SILVER_VN via PNJ / Phú Quý / VNAppMob).

## Why it exists
In the daily ingest gate, the `vn_domestic` group is **non-critical** on purpose — a dead
scraper endpoint must never fail the futures feed (see `docs/etl/vn-prices-daily-ingest.md`).
So VN staleness only shows as a WARNING in the daily log and can rot unnoticed. This monitor
promotes that WARNING into its own red/green signal without coupling it to futures.

## What it does
- Workflow: `.github/workflows/vn-freshness-monitor.yml`.
- Runs `python scripts/check_freshness.py --group vn_domestic --strict`.
  - `--group vn_domestic` — scoped to the VN group only; futures are not evaluated here.
  - `--strict` — a stale non-critical group **fails** (exit 1) instead of merely warning.
- **Read-only**: the gate is a `SELECT max(price_date)` per commodity. It never ingests,
  never writes, never touches migrations/RLS. Reads `DATABASE_URL` from the repo secret;
  the URL is never printed.
- Triggers: `schedule` (cron `30 1 * * *`, 01:30 UTC ≈ 08:30 ICT, after the 22:00 UTC VN
  ingest lands) + `workflow_dispatch` (manual run from the Actions tab). It does **not** run
  on push/PR.

## When it goes red
A VN group is STALE when the latest `price_date` across its commodities is older than
`max_gap_days` (4, in `configs/ingestion/sources.yaml → monitoring.groups`). Under normal
operation GOLD_VN (PNJ, same-day) and SILVER_VN (Phú Quý, same-day) stay well within 4 days,
so red means the scrapers have been failing for several days.

## Triage when red
1. Inspect the daily ingest run (`.github/workflows/ingest.yml`) logs for the
   `Ingest VN domestic prices` step — it is `continue-on-error`, so it can be failing quietly.
2. Check the connector + parser fixtures: `etl/sources/market/vn_domestic.py`
   (PNJ JSON / Phú Quý HTML / VNAppMob JSON) — a Cloudflare block or a format change is the
   usual cause.
3. Confirm the DB directly: `SELECT max(price_date)` for `GOLD_VN` / `SILVER_VN` in
   `fact_price_daily`.
4. Adjust tolerance in config if the change is intentional (e.g. a long holiday) — `max_gap_days`
   is config-driven, no code change needed.

## Run it locally
```bash
python scripts/check_freshness.py --group vn_domestic --strict   # VN-only, strict (exit 1 if stale)
python scripts/check_freshness.py --strict                       # all groups, strict
python scripts/check_freshness.py                                # daily gate: futures critical, VN warn
```
An unknown `--group` name is a hard error (exit 2) so a typo cannot silently pass green.
