---
name: backfill-price-history
description: Download or load historical price history into fact_price_daily for a commodity. Covers deep Yahoo/yfinance backfill for futures, historical CSV import, and the today-only reality of domestic scrapers (which have no backfill and must accumulate forward). Use when the user asks to download / load / backfill price history ("tải lịch sử giá"), or when a newly-added commodity needs history before it can be forecast. Follows the add-commodity skill.
---

# Backfill price history

Forecasting needs enough history: `ml/forecast.py` returns `available: false` until a
series has `MIN_HISTORY` positive points. This skill gets that history in.

## Which path applies
| Source type | History available? | How |
|---|---|---|
| Yahoo futures/ETF (`sources.yaml` `prices`) | ✅ years | yfinance deep backfill |
| Historical CSV (Kaggle/Agmarknet/user file) | ✅ as long as the file | `--csv-import` |
| Domestic scraper (`vn_prices`) | ❌ today only | accumulate forward (no backfill) |

## A. Yahoo deep backfill (futures/ETF)
The commodity must already be in `sources.yaml` → `prices.instruments`. Then:
```
python -m etl.ingest --backfill --sources prices --period max   # or 10y / 1y
```
- `--backfill` uses the fast append path: `ON CONFLICT DO NOTHING`, **idempotent** (safe to
  re-run; revised recent closes don't abort the batch).
- To limit blast radius while testing, narrow with a smaller `--period` first and read the
  row counts before going `max`.
- The daily job runs `--backfill --sources prices --period 1mo`; a one-off deep history is a
  manual `--period max` run.

## B. Historical CSV import
1. Put the file under `data/` (gitignored for large data — confirm it's not committed).
2. Add an entry to `configs/ingestion/csv_imports.yaml` under `imports:` —
   `path`, `commodity_code`, `instrument_code`, `currency`, `value_column`, `date_column`,
   `date_format`, optional `commodity_column`/`commodity_filter` (multi-commodity files),
   `aggregate` (e.g. `median` for per-market rows), optional `market_column`/`market_filter`.
3. Run:
```
python -m etl.ingest --csv-import <import_name>
```
   (idempotent `ON CONFLICT` backfill). Copy a working entry (onion/chilli/coffee) as a template.

## C. Domestic scraper (no history)
There is **no backfill** — these endpoints publish only today's price. The only way to build
history is to **wire the source into the daily ingest job and let it accumulate** one point
per instrument per trading day. Be explicit with the user: a useful forecast is weeks-to-months
away, not immediate. (If they need history sooner, fall back to a user CSV — path B.)

## Verify (read-only, never print secrets)
- Freshness: `python scripts/check_freshness.py`.
- Row counts per commodity on its primary instrument (read-only query); confirm the date range
  and that values are positive.
- Re-run the same backfill once — inserted should be ~0 (idempotency proof).
- Point-in-time safety: backfill must not introduce look-ahead; `release_lag_days` governs when
  a close becomes "available". Don't backfill a future-dated row.

## After history exists
Re-run a forecast for the commodity (`ml.forecast.forecast_commodity`) to confirm it flips from
`available: false` to a real best-of model with a backtest MAPE. Production writes of the
forecast log stay in their own controlled phase (see the forecast writer/evaluator docs).
