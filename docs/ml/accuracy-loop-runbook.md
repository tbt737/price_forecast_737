# Accuracy loop — scheduled runbook (ACC-2)

The accuracy loop turns live forecasts into a measured track record. It has two halves,
each a dedicated GitHub Actions workflow. Both write to **`fact_forecast_log` only** — they
never ingest prices, migrate, or touch any other table — and both use real exit codes
(a failure turns the run red; nothing is swallowed).

## Writer — `.github/workflows/accuracy-writer.yml`
- **Trigger**: `workflow_run` after **Daily ingestion** completes **successfully**
  (`conclusion == 'success'`), plus manual `workflow_dispatch`. Not on push/PR.
- **Command**: `python scripts/write_forecast_log.py --write`.
- **What it does**: snapshots each approved commodity's current 30/90-day forecast into
  `fact_forecast_log` as a `pending` row (predicted vs baseline, model_used, backtest
  metadata). **Idempotent** — `ON CONFLICT (commodity_code, as_of_date, target_date,
  horizon_days, model_used) DO NOTHING`, so a same-day rerun inserts 0.
- Runs `ml.forecast.forecast_commodity` directly (no HTTP), so the SEC-2 internal key is
  not involved. A commodity with `< MIN_HISTORY` (e.g. GOLD_VN today) is skipped, not an error.

## Evaluator — `.github/workflows/accuracy-evaluator.yml`
- **Trigger**: weekly cron `0 3 * * 1` (Mondays 03:00 UTC) + manual `workflow_dispatch`.
- **Command**: `python scripts/evaluate_forecast_log.py --write`.
- **What it does**: for matured `pending` rows (`target_date <= today`), reads the real
  price on the same primary instrument and fills `actual_price` + `absolute_error` +
  `absolute_percentage_error`, flipping status to `evaluated`. A row still without a real
  price past `--expire-after-days` (default 7) becomes `expired`. **Never fabricates an
  actual**; `--grace-days` (default 4) tolerates a weekend/holiday target.

## Reading the results
```sql
-- coverage + accuracy by commodity/horizon (evaluated rows only)
SELECT commodity_code, horizon_days,
       count(*) FILTER (WHERE status='evaluated') AS evaluated,
       count(*) FILTER (WHERE status='pending')   AS pending,
       count(*) FILTER (WHERE status='expired')   AS expired,
       round(avg(absolute_percentage_error) FILTER (WHERE status='evaluated')::numeric, 2) AS avg_ape
FROM fact_forecast_log
GROUP BY commodity_code, horizon_days
ORDER BY commodity_code, horizon_days;
```

## Operating notes
- **Manual dry-run first** (no `--write`) before trusting a change:
  `python scripts/write_forecast_log.py` / `python scripts/evaluate_forecast_log.py` —
  both default to dry-run and print exactly what they *would* write.
- **Exit codes**: `0` success (0 rows is a valid idempotent/no-op outcome), `2` bad
  arguments, non-zero on an unhandled failure (e.g. DB unreachable) → red run.
- **Baseline accrues slowly**: h=30/90 rows only mature after 30/90 business days, so the
  first `evaluated` rows appear ~6 weeks (h=30) / ~18 weeks (h=90) after the writer starts.
- **No holiday calendar**: `target_date` is business-days-ahead (skips weekends only); the
  evaluator's grace window absorbs a holiday shift.
- Both workflows require the `DATABASE_URL` repo secret (shared with the ingest workflow);
  the URL is never printed.
