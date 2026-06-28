# Forecast accuracy evaluator (`scripts/evaluate_forecast_log.py`, Phase ACC-1D-A)

Fills `actual_price` + errors and flips `status` for matured `pending` rows in
`fact_forecast_log` once the real price is available. Pairs with the writer
(`forecast-writer.md`); together they close the live accuracy loop.

## Dry-run by default

- **Default mode is dry-run**: it reads pending rows, looks up actuals, decides, and
  prints a summary — **updates nothing**.
- **`--write` is required to update.** The first controlled production `--write` is a
  separate audited phase. Output is a safe summary; **`DATABASE_URL`/secrets are never
  printed**.

```
python scripts/evaluate_forecast_log.py                       # dry-run, due rows, today
python scripts/evaluate_forecast_log.py --commodities GOLD --horizons 30 --limit 5
python scripts/evaluate_forecast_log.py --write              # apply (later audited phase)
```

CLI: `--write`, `--as-of YYYY-MM-DD` (default today), `--commodities CODE…`, `--horizons 30 90`,
`--limit N`, `--grace-days N` (accept nearest next actual within N days, default 4),
`--expire-after-days N` (default 7).

## Which rows are evaluated

Only rows with `status='pending'` **and** `target_date <= as_of` (matured), after the
optional commodity/horizon filters and limit. Non-pending rows are never touched.

## Actual lookup (never fabricated)

The actual is read from `fact_price_daily` on the commodity's **primary instrument**
(the most-priced series — the same one the forecast was made from):

- prefer the price **on `target_date`**;
- if `target_date` was a weekend/holiday with no price, accept the **nearest *next*
  trading day within `--grace-days`** (never a date *before* the target, never beyond
  the grace window);
- if no price is found within grace, **no actual is invented** — the row stays `pending`.

## Evaluation calculation

When an actual `> 0` is found: `absolute_error = |actual − predicted|`,
`absolute_percentage_error = absolute_error / actual × 100`; the row is set to
`actual_price`, `actual_available_at = now()`, the two error columns,
`status = 'evaluated'`, `evaluated_at = now()`.

## Expiry (frozen / never-arriving actuals)

If `target_date` is older than `--expire-after-days` and no actual exists, the row is
`expired` (only on `--write`; dry-run reports *would-expire*). Error fields are left
NULL — an expired row is **not** an accuracy data point.

> The existing ROBUSTA row (`as_of 2026-04-20`, `target 2026-06-01`, on frozen produce
> data) has no actual → it would be **expired, not evaluated**. A stale/frozen commodity
> is never fake-evaluated.

## Idempotency & safety

Every update targets a single row by `forecast_log_id` **and guards `status='pending'`**,
so a row is never updated twice and only pending rows change. No `DELETE`, no broad
`UPDATE`. Dry-run executes zero updates.

## Accuracy is only known after evaluation

A `pending` row carries no accuracy. Reports must aggregate only `evaluated` rows and
surface how many are still `pending`/`expired`.
