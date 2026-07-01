# VNAppMob historical VN gold source (VN-PRICE-2A)

An **additive** historical source for `GOLD_VN` — instrument `VNAPPMOB_SJC_1L`, source
`VNAPPMOB`. It gives GOLD_VN real multi-month SJC history to eventually forecast from,
**without** replacing the PNJ / Phú Quý live spot connectors.

## Source
- API: VNAppMob Gold v2, endpoint `…/api/v2/…/sjc`, date-range via `date_from` / `date_to`
  (Unix seconds). Value = `sell_1l` (SJC 1 lượng sell, full VND); `buy_1l` kept in record
  `attributes` for lineage.
- **Depth observed:** ~**117 daily rows**, span 2026-01-23 → present (the API's data start).
- Config: `configs/ingestion/sources.yaml` → `vn_history`. Parser FORMAT `vnappmob_gold` in
  `etl.sources.market.vn_domestic.HISTORY_PARSERS`.

## API key handling (no secret stored)
The free token is **minted per run** from the keyless request-key endpoint (`key_url`) and used
only as the `Authorization` header. It is **never** stored, committed, logged, printed, or placed
in any record / provenance / metadata. Tests assert the token never leaks into records. (Tokens
expire ~15 days — irrelevant since we mint fresh each run.)

## Range behavior
- Requests are split into ≤ `chunk_days` (default 300) windows (the API caps very wide ranges).
- Fail-closed: a bad key, non-JSON body, or malformed chunk is skipped — never fabricates a date;
  only source-observed dates are recorded (bucketed as UTC calendar dates).

## Running
- **Dry-run (no write):** `python -m etl.ingest --sources vn_history --history-days 450` — mints a
  token, fetches, maps in memory, writes nothing. Not part of the daily `all` run.
- **Backfill (LATER, audited phase VN-PRICE-2B):** the controlled `--write` that actually inserts
  the ~117 rows into `fact_price_daily`.

## Forecasting note
`MIN_HISTORY = 252` (unchanged). Even after backfilling ~117 rows, GOLD_VN stays **below** the
forecast threshold — it will forecast only once ~252 points accumulate (≈ another ~135 trading days
via the daily `vn_prices` step), or if `MIN_HISTORY` is lowered in a separate, backtested ML phase.
No `MIN_HISTORY` change is made here.
