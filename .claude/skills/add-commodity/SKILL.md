---
name: add-commodity
description: Onboard a new commodity into this multi-commodity price-forecast platform the config-over-code way — create its YAML profile, register a price source, seed it, write offline tests, satisfy the two architecture guards, and bump the inventory-count tests. Use whenever the user asks to add / track / forecast a new commodity, metal, ticker, or domestic price ("thêm loại hàng để dự đoán giá", "thêm giá X", "add commodity X"). Pairs with the find-price-source and backfill-price-history skills.
---

# Add a commodity to the forecast platform

This repo is a **generic, configuration-driven** platform. A new commodity is onboarded
by **adding config + a profile**, never by branching engine code on a commodity name.
Read `CLAUDE.md` and `ARCHITECTURE.md` first. **Never edit `ml/forecast.py`, `ml/models/**`,
or the planner/writer to fit one commodity.**

Work in phases like the rest of this project: build + offline-test + prove on real data
in one phase; the **first production DB write is a separate controlled phase** (dry-run
first, idempotent `ON CONFLICT`, read-only verification).

## Step 0 — Pick the data source
Invoke the **find-price-source** skill. You must know *where the daily price lives*
(Yahoo ticker / JSON API / HTML scrape / user CSV) before writing anything. Capture a
real response as a fixture for offline tests.

## Step 1 — Create the commodity profile
`configs/commodities/<commodity_code>.yaml`. Copy the shape of an existing profile that
matches the type (`gold.yaml` for a metal/macro asset, `robusta.yaml` for a crop). Rules:
- `commodity_code` UPPER_SNAKE and unique; `instrument_code`s UPPER and unique.
- **Every list section must be present and non-empty** (`market_instruments`,
  `weather_regions`, `production_regions`, `consumption_regions`, `export_regions`,
  `import_regions`, `physical_drivers`, `macro_drivers`, `logistics_drivers`,
  `event_risk_drivers`, `data_sources`, `models`, `notes`). Non-price-driver sections
  (e.g. weather for a metal) use a `GLOBAL_NA` placeholder row, as `gold.yaml` does.
- Domestic VN commodity ⇒ distinct code from any international one (e.g. `GOLD_VN` vs `GOLD`).

## Step 2 — Register the price source in `configs/ingestion/`
- **Yahoo futures/ETF** → add a row to `sources.yaml` → `prices.instruments`
  (`commodity_code`, `instrument_code`, `ticker`, `currency`).
- **Domestic / scraped spot** → add a row to `sources.yaml` → `vn_prices.endpoints`
  (`parser`, `url`, `product_key`, `currency`). The `parser` names a **FORMAT** in
  `etl/sources/market/vn_domestic.py` `PARSERS` (e.g. `pnj_json`, `phuquy_silver_html`) —
  never a per-commodity branch. New format ⇒ add a parser function there.
- **Historical CSV** → add an entry to `csv_imports.yaml` (see backfill-price-history).

## Step 3 — Wire a NEW connector (only if a new source type)
If you added a brand-new connector module under `etl/sources/`:
- Add its spec dataclass + a loader block in `etl/ingestion/config.py`
  (and the new list field on `IngestionConfig` + its `source_codes` union).
- Dispatch it in `etl/ingest.py` `build_connectors(...)` and add the key to the
  `--sources` argparse `choices`.
- Add any new `source_code` to `db/seeds/seed_ingestion_sources.py` (`INGESTION_SOURCES`).
- Keep network I/O **inside** the fetch function; make `fetch` injectable so tests are offline.

## Step 4 — Satisfy the TWO architecture guards (they WILL fail otherwise)
1. **No hardcoded commodity** (`tests/quality/test_etl_contracts.py::test_etl_code_is_generic…`
   + the planner-contract twin). `SINGLE_COMMODITY_TOKENS` =
   `("robusta","gold","copper","rice","corn","wheat","cocoa","sugar","soybean")` — none of
   these may appear as a **whole word** anywhere in `etl/` code, **including docstrings/comments**.
   Keep connector prose generic (say "a JSON feed", not "a gold feed"). Underscored tokens
   like `phuquy_silver_html` are fine (no word boundary).
2. **No network in core** (`…::test_core_pipeline_needs_no_network[_or_credentials]`). A
   connector that does network I/O is the *sanctioned* boundary — register its file path in
   `NETWORK_EXEMPT` in **both** `tests/quality/test_etl_planner_contract.py` and
   `tests/quality/test_etl_contracts.py` (alongside `yahoo.py`).

## Step 5 — Bump the inventory-count tests
Adding N commodities / M instruments changes fixed counts. **Run the suite first to read the
exact new numbers — do not guess.** Update:
- `tests/quality/test_profiles_quality.py` (profile-file count)
- `tests/integration/test_schema_and_load.py` (`profile:loaded`, `DimCommodity`,
  `CommodityProfileRegistry`, `DimMarketInstrument`)
- `apps/api/tests/test_loader.py` (same counts)
- `apps/api/tests/test_api.py` (`/commodities`, `/profiles`, `/stats` counts)
- The generated `db/views/generated/010_mv_ml_daily_features_wide.sql` **auto-regenerates**
  with the new driver `metric_code`s — keep the regenerated file (it's expected, not pollution).

## Step 6 — Offline tests for the connector
Add a test (e.g. `tests/integration/test_<source>_source.py`) that loads the **captured
fixture**, injects it as `fetch`, and asserts `collect()` yields the right
`NormalizedRecord`s (commodity/instrument/value/currency/observation_date), plus parser
unit tests (exact value on a tiny synthetic snippet, `None` on missing product, fail-soft
on fetch error, unknown-format skipped). **No live network in tests.**

## Step 7 — Verify (trust but verify)
- `python -m pytest -q tests/ apps/api/tests/ ml/tests/` — all green.
- `python -m py_compile` the changed Python files.
- **Live proof, no DB write:** construct the connector with the real fetch and print
  `collect()` records (use `sys.stdout.reconfigure(encoding="utf-8")` on Windows for VN text).
- Secret scan the changed files; confirm no `.env`/secret/`uv.lock` staged.

## Step 8 — Hand off to the controlled production phase
Do **not** silently seed/write production here. The next phase (separate, audited) seeds the
commodity into the DB, wires the source into the daily ingest job, and does the first
`--write` (dry-run first, idempotent, read-only verification). For **history**, invoke
**backfill-price-history**. ⚠️ Domestic scrapers are *today-only* — forecasting only becomes
meaningful after enough daily history accumulates (`ml/forecast.py` `MIN_HISTORY`); say so
plainly to the user.

## Definition of done
Config + profile added; guards pass; counts bumped to the real numbers; offline tests pass;
live parse proven without a DB write; no engine edited for one commodity; production write
left to its own phase. Report what was added and what is intentionally deferred.
