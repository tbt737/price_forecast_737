# VN domestic prices in the daily ingest (VN-PRICE-1D)

The daily workflow (`.github/workflows/ingest.yml`) ingests Vietnam domestic spot prices
(GOLD_VN via PNJ, SILVER_VN via Phú Quý) as a **non-blocking** step so the series can
accumulate history.

## Behavior
- Runs **after** the critical futures price step, as its own step:
  `python -m etl.ingest --sources vn_prices --write`.
- **Non-blocking**: `if: always()` + `continue-on-error: true`. PNJ/Phú Quý are scraped/live
  endpoints — a Cloudflare block, a format change, or a timeout must **never** fail the futures
  feed or turn the run red on its own.
- Uses the write path (`ON CONFLICT DO NOTHING`), **not** `--backfill`: these endpoints publish
  only *today's* price, so each run writes at most one row per instrument (idempotent — a rerun
  the same day inserts 0).
- **Not part of the freshness gate.** `scripts/check_freshness.py` only asserts the *futures*
  commodities advanced; VN prices are intentionally excluded for now, so a missing VN day cannot
  fail CI.

## Monitoring (separate from CI green/red)
Because the VN step is non-blocking, a silently missing VN day will **not** show up as a red run.
Monitor VN coverage separately — e.g. periodically check that `fact_price_daily` has a recent row
for `GOLD_VN` / `SILVER_VN`:
- 0 new rows for several trading days ⇒ an endpoint likely changed shape or is blocked → inspect
  the connector (`etl/sources/market/vn_domestic.py`) and the parser fixtures.

## No forecast yet
GOLD_VN/SILVER_VN start with one row per day. A useful forecast only appears once enough daily
history accumulates (`ml/forecast.py` `MIN_HISTORY`); until then the API reports them unavailable.
Promoting VN prices into the freshness gate is a **later** decision, once the daily feed is proven
stable over time.
