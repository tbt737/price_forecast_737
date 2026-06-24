# Automated data ingestion

Config-driven, real-source data collection that flows through the existing
fail-closed pipeline (connector → provenance gate → transaction-safe `write_batch`).
No symbols are hardcoded — everything is read from `configs/ingestion/sources.yaml`.

## Connectors
| Connector | Feeds | Source | Key? |
| --- | --- | --- | --- |
| `etl/sources/market/yahoo.py` `YahooPriceSource` | `fact_price_daily` | Yahoo Finance (yfinance) | none |
| `etl/sources/weather/nasa_power.py` `NasaPowerSource` | `fact_weather_daily` | NASA POWER daily API | none |

Each row becomes a `NormalizedRecord` with deterministic provenance
(`source_record_id = "<source>:<ticker|region:metric>:<date>"`,
`source_payload_hash` = canonical SHA-256). The HTTP fetch is injectable, so tests
never touch the network.

## CLI
Reads `DATABASE_URL` (env var, else repo-root `.env`). **Default is dry-run.**

```bash
python -m etl.ingest                      # dry-run: fetch + plan, write nothing
python -m etl.ingest --write              # persist
python -m etl.ingest --write --sources prices --period 1mo
python -m etl.ingest --write --sources weather --weather-days 30
```

It seeds the `yahoo` / `NASA_POWER` source rows, runs every configured connector
through the provenance gate, then writes accepted records atomically.

## Guarantees
- **Point-in-time:** `release_date = observation_date + release_lag_days` (config:
  1 day for prices, 3 for weather) — no look-ahead.
- **Idempotent:** re-running is safe; provenance + grain make replays no-ops.
- **No silent overwrite:** the *same* source record with a *changed* value →
  conflict (not overwrite). Intraday price re-runs will conflict because today's
  close is still moving; use a `revision` bump for a deliberate restatement.
- **Atomic:** any reject/conflict rolls back the whole batch.

## Adding a commodity / source
Edit `configs/ingestion/sources.yaml` only (instrument→ticker, region→coordinates).
Unknown instrument/region codes are rejected cleanly by the pipeline, never crash.

## Scheduling
### Option A — GitHub Actions (cloud cron) — `.github/workflows/ingest.yml`
Runs daily at 22:00 UTC and on manual dispatch. **Requires** pushing the repo to
GitHub and adding a repository secret `DATABASE_URL` (Settings → Secrets and
variables → Actions). Runs even when your PC is off.

### Option B — Windows Task Scheduler (local) — runs on this machine
Create a daily task that runs the CLI (machine must be on; uses repo-root `.env`):

```powershell
schtasks /Create /TN "CQP Daily Ingest" /SC DAILY /ST 18:00 ^
  /TR "cmd /c cd /d \"D:\AI Project\DỰ BÁO GIÁ CẢ HÀNG NÔNG SẢN\" && python -m etl.ingest --write" /F
```

Remove it with `schtasks /Delete /TN "CQP Daily Ingest" /F`.

> Supabase `pg_cron` / Edge Functions are **not** used: ingestion is Python
> (external fetch + ETL pipeline), which those runtimes can't execute.
