# Shadow forecast-log writer (`scripts/write_forecast_log.py`, Phase ACC-1C-A)

Writes `pending` rows into `fact_forecast_log` (see `forecast-accuracy-log.md`) from
the existing production forecaster. It is **shadow logging**: it records what the
models predicted today so accuracy can be measured later — it never changes the
forecaster, the API, or the ETL pipeline.

## Dry-run by default

- **Default mode is dry-run**: the writer reads prices, computes forecasts, and prints
  a summary, but **inserts nothing**.
- **`--write` is required to insert.** The *first* controlled production `--write` is a
  separate audited phase (**ACC-1C-B**); ACC-1C-A ships the code + offline tests only.
- Output is a safe summary — **`DATABASE_URL`/secrets are never printed**.

```
python scripts/write_forecast_log.py                       # dry-run, approved commodities, h=30/90
python scripts/write_forecast_log.py --commodities ROBUSTA --horizons 30 --limit 1
python scripts/write_forecast_log.py --write              # insert (ACC-1C-B only)
```

CLI: `--write`, `--commodities CODE…` (allowlist; default = approved set), `--horizons 30 90`
(allowlisted), `--as-of YYYY-MM-DD` (only log forecasts anchored on that date; default =
each commodity's latest price date), `--limit N` (cap commodities for smoke).

## Row mapping

Per commodity × horizon, one row from `forecast_commodity(...)`:
`predicted_price` = the horizon-end forecast point; `baseline_price` = the naive last value;
`as_of_date` = the forecast's `last_date`; `target_date` = business-day target (below);
`model_used` = the chosen model; `status` = `pending`; `metadata_json` = `{candidates,
ou_considered, mape_pct, naive_mape_pct, beats_naive, source, run_mode, version}`;
`actual_price` / errors / `evaluated_at` stay NULL.

## Target-date logic (business-day approximation)

`target_date = business_days_ahead(as_of_date, horizon_days)` — the n-th **weekday** after
the anchor (skips Sat/Sun), matching the forecaster's own trajectory dates.

> ⚠️ **Limitation:** no market-**holiday** calendar is applied. On a holiday the true
> trading day differs by a day, so `target_date` may land on a non-trading day; the
> evaluator (later phase) must tolerate this (e.g. match the nearest available actual).

## Idempotency

`--write` uses `INSERT … ON CONFLICT (commodity_code, as_of_date, target_date,
horizon_days, model_used) DO NOTHING` — re-running the same day inserts nothing new and
**never updates** existing rows. Inserted/skipped counts are reported.

## Safety / robustness

- A single unavailable or failing commodity is **skipped and reported**, not crashed —
  the batch continues (unless every commodity fails).
- Backtest results are **not** logged as forecasts (only live `forecast_commodity` output).
- `predicted_price ≤ 0` rows are dropped (honours the table `CHECK`).

## Accuracy is not known yet

Every row written is `pending`. **No accuracy claim is valid until a later evaluator
fills `actual_price` and flips `status` to `evaluated`** — reports must count pending rows
and only aggregate evaluated ones.
