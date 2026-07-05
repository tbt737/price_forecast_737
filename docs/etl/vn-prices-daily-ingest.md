# VN domestic prices in the daily ingest (VN-PRICE-1D)

The daily workflow (`.github/workflows/ingest.yml`) ingests Vietnam domestic spot prices
(GOLD_VN via PNJ, SILVER_VN via Phú Quý) as a **non-blocking** step so the series can
accumulate history.

## Behavior
- Runs **after** the critical futures price step, as its own step. Two commands (per ETL-VN-3):
  `python -m etl.ingest --backfill --sources vn_prices` (today's PNJ/Phú Quý spot) then
  `python -m etl.ingest --backfill --sources vn_history --history-days 7` (VNAppMob SJC top-up so
  the forecast-primary series self-heals any recently-missed day).
- **Non-blocking**: `if: always()` + `continue-on-error: true`. PNJ/Phú Quý are scraped/live
  endpoints — a Cloudflare block, a format change, or a timeout must **never** fail the futures
  feed or turn the run red on its own.
- Uses the **backfill** path (per-record `ON CONFLICT DO NOTHING`), **not** the all-or-nothing
  `--write` batch: these endpoints publish only *today's* price, so a single provenance conflict
  (e.g. a same-day rerun after a revised price) must not roll back and drop the other instruments'
  rows. Each run inserts at most one new row per instrument; a same-day rerun inserts 0 (idempotent).
- **Non-critical in the freshness gate.** `scripts/check_freshness.py` treats the `vn_domestic`
  group as non-critical, so a missing VN day is a WARNING in the daily gate (not a red run). A
  dedicated strict monitor turns VN staleness red on its own — see `vn-freshness-monitor.md`.

## Monitoring (separate from the daily CI green/red)
Because the VN step is non-blocking, a silently missing VN day will **not** turn the daily run red.
That is what the dedicated **VN freshness monitor** is for
(`.github/workflows/vn-freshness-monitor.yml`, see `vn-freshness-monitor.md`): it runs
`check_freshness.py --group vn_domestic --strict` on a schedule and goes red when the VN series is
stale beyond its `max_gap_days`.
- 0 new rows for several trading days ⇒ an endpoint likely changed shape or is blocked → inspect
  the connector (`etl/sources/market/vn_domestic.py`) and the parser fixtures.

## No forecast yet
GOLD_VN/SILVER_VN start with one row per day. A useful forecast only appears once enough daily
history accumulates (`ml/forecast.py` `MIN_HISTORY`); until then the API reports them unavailable.
VN prices are now in the freshness gate as a **non-critical** group with a dedicated strict monitor
(`vn-freshness-monitor.md`); a real forecast still waits on accumulated daily history.
