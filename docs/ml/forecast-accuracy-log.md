# Forecast accuracy log — `fact_forecast_log` (Phase ACC-1A)

This is the schema + contract for **live / shadow forecast accuracy tracking**. It is
the foundation of the Weekly Accuracy Evaluation feature. **Phase ACC-1A delivers the
schema, contract and offline tests only** — the migration is **not applied**, and no
forecast-logging or evaluation job is enabled yet (those are later phases).

## What this is (and is not)

- **It is forward / out-of-sample tracking of *real* predictions.** Each row records a
  forecast the production pool actually made on `as_of_date` for a future `target_date`,
  and — once that date arrives — how close it was to the *actual* price.
- **It is NOT a backtest.** Backtests (walk-forward MAPE vs naive, in `ml/backtests/`)
  estimate accuracy on historical data. This log measures accuracy on genuinely future
  prices that did not exist when the forecast was made. The two are complementary.

## Write-first, evaluate-later lifecycle

```
1. WRITE  (forecast time)   status = 'pending'
   predicted_price / baseline_price recorded; actual_price is NULL.
2. EVALUATE (later, when the actual for target_date is in fact_price_daily)
   fill actual_price, absolute_error, absolute_percentage_error, evaluated_at
   → status = 'evaluated'.
3. EXPIRE   if the actual never becomes available within a reasonable window
            → status = 'expired'.
4. INVALID  if the forecast row is malformed / superseded → status = 'invalid'.
```

**No accuracy claim is valid until `actual_price` is present (`status='evaluated'`).** A
freshly written batch is all `pending` and says nothing about accuracy yet — reports must
filter to evaluated rows and account for how many are still pending.

## Table contract

| Column | Type | Notes |
|---|---|---|
| `forecast_log_id` | SERIAL PK | |
| `forecast_run_id` | VARCHAR(64) | batch id of the run that produced the forecast |
| `commodity_code` | VARCHAR(40) | e.g. `ROBUSTA` (string code, not key) |
| `as_of_date` | DATE | anchor / last-price date the forecast was made from |
| `target_date` | DATE | the predicted business date (`> as_of_date`) |
| `horizon_days` | INTEGER | allowlisted to **30 or 90** |
| `model_used` | VARCHAR(40) | `ridge_ar` / `gbm` / `gbm_cyc` / `ou` / `naive` |
| `predicted_price` | NUMERIC(20,6) | **> 0** |
| `baseline_price` | NUMERIC(20,6) | naive (last-value) reference |
| `actual_price` | NUMERIC(20,6) NULL | filled at evaluation |
| `actual_available_at` | TIMESTAMPTZ NULL | when the actual landed |
| `absolute_error` | NUMERIC(20,6) NULL | `|actual − predicted|` |
| `absolute_percentage_error` | NUMERIC(20,6) NULL | `100·|actual − predicted| / actual` |
| `status` | VARCHAR(20) | `pending` \| `evaluated` \| `expired` \| `invalid` |
| `metadata_json` | JSONB | free-form (e.g. band, backtest MAPE at forecast time) |
| `created_at` | TIMESTAMPTZ | default `now()` |
| `evaluated_at` | TIMESTAMPTZ NULL | |

### Constraints

- `CHECK (predicted_price > 0)`
- `CHECK (horizon_days IN (30, 90))`
- `CHECK (target_date > as_of_date)`
- `CHECK (status IN ('pending','evaluated','expired','invalid'))`
- `UNIQUE (commodity_code, as_of_date, target_date, horizon_days, model_used)` — one row
  per (commodity, anchor, target, horizon, model); re-logging the same forecast is a no-op.

### Indexes

- `ix_forecast_log_pending` — partial on `target_date WHERE status = 'pending'` (the
  evaluation job scans matured pending rows).
- `ix_forecast_log_commodity_asof` — per-commodity history.
- `ix_forecast_log_target_date` — maturity scans.

## Safety / scope of ACC-1A

- The migration `db/migrations/003_forecast_log.sql` is **additive + idempotent** (CREATE
  IF NOT EXISTS, no DROP) and is **not applied** in this phase.
- **No production DB write, no Supabase connection, no live forecast job** is introduced.
- ML model logic, the ETL daily workflow, and the API are **unchanged**.
- Later phases (separately approved) will add: the forecast-logging writer (write `pending`
  rows when forecasts run), the evaluation job (fill actuals weekly), and the read-only
  accuracy surface.
