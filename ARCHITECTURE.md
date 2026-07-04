# ARCHITECTURE — Multi-Commodity Quant Forecasting Platform

> **Status:** Phases 1–9 implemented. 18 commodity profiles; star schema + loaders;
> ETL connectors (Yahoo prices, NASA POWER weather, config-driven CSV/Agmarknet
> imports) with a fail-closed provenance gate; ML forecasting (Ridge AR + XGBoost,
> multi-scale Cobweb cycle harmonics with wavelet stability, anchored damped-trend
> Fourier baseline) chosen per-commodity by walk-forward backtest with an honest
> naive fallback; FastAPI service (cached forecasts) + Next.js dashboard with a
> forecast-compare view; daily GitHub Actions ingest. Outstanding: macro/logistics/
> S&D/event-driver connectors (Phase 3B), model
> registry (Phase 7), and productionization (Phase 10 — Dockerfile + DEPLOY.md
> exist; cloud hosting pending). See `DEPLOY.md` to go live.

---

## 1. Vision

Build a **generic, configuration-driven** AI forecasting platform that can model the
price of *any* commodity — agriculture, energy, metals — or *any* macro/logistics
indicator, without ever hardcoding business logic for a single commodity.

The system scales horizontally by **adding a YAML profile**, not by adding code.
A new commodity is onboarded by dropping a file into `configs/commodities/` (and a
mirror in `db/commodity_profiles/`); the ETL, feature engineering, and model layers
read that profile and act generically.

### Core principle — never hardcode a single commodity

Every piece of business logic is keyed on **identifiers**, never on names:

| Identifier      | Meaning                                                        |
| --------------- | ------------------------------------------------------------- |
| `commodity_id`  | The thing being forecast (robusta, gold, crude_oil, …)        |
| `instrument_id` | A tradable/market series (e.g. ICE Robusta `RC`, COMEX `GC`)  |
| `region_id`     | A geography (production, consumption, export, import, weather) |
| `metric_code`   | A measured quantity (spot_price, rainfall_mm, open_interest…) |

If a feature, query, or model references a literal commodity name in code, that is a
**bug**. The name lives in the profile; the code sees only IDs and metric codes.

---

## 2. Multi-commodity design

```
                       configs/commodities/*.yaml
                                  │  (declarative profile = source of truth)
                                  ▼
        ┌─────────────────────────────────────────────────────────┐
        │  PROFILE LOADER  (validates schema → registers entities) │
        └─────────────────────────────────────────────────────────┘
             │              │               │              │
             ▼              ▼               ▼              ▼
        instruments    regions         drivers        data_sources
             │              │               │              │
             ▼              ▼               ▼              ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  ETL  (sources/* fetch → loaders/* normalize → observations)   │
   └───────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  NORMALIZED DB  (commodity / instrument / region / observation)│
   └───────────────────────────────────────────────────────────────┘
                                  │
                                  ▼  (point-in-time materialized views)
   ┌───────────────────────────────────────────────────────────────┐
   │  ML  (features → models → backtests → registry)                │
   └───────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  API (FastAPI)  ──>  WEB (Next.js / Plotly / ECharts)          │
   └───────────────────────────────────────────────────────────────┘
```

Each commodity profile declares which **driver groups** apply to it:

- `physical_drivers` — supply/demand fundamentals (stocks, yields, crush margins…)
- `macro_drivers` — FX, rates, inflation, risk-on/off, related commodity prices
- `logistics_drivers` — freight rates, port congestion, basis/spreads
- `event_risk_drivers` — weather shocks, geopolitics, policy/tariff, disease

The same engine handles a soft commodity (robusta) and a metal (gold) because both
are just a *set of instruments + regions + drivers + sources* described in YAML.

---

## 3. Database design

### 3.1 Dimensional (star) schema

> **Implemented in Phase 2.** Source of truth = `apps/api/app/models/` (`dimensions.py`,
> `facts.py`); mirrored by the Alembic migration
> `apps/api/app/migrations/versions/0001_initial_star_schema.py`. The service that owns
> this schema is the FastAPI app under `apps/api/app/`.

A star schema: surrogate-keyed **dimensions** + a **profile registry**, plus one fact
table **per data domain**. Dimensions are global and deduplicated by their natural code
(a region/source shared by many commodities is stored once). `dim_market_instrument` is scoped
to a commodity because the same `instrument_code` (e.g. `CN_FOB_QINGDAO`) denotes
different goods for different commodities. Metric/indicator granularity is carried as
`*_code` text columns on the facts, so a new metric is new rows — never a schema change.

The 12 approved physical tables (source of truth = `apps/api/app/models/`; raw SQL
mirror = `db/migrations/001_core_schema.sql`):

```
-- Dimensions + region map + registry
dim_commodity(commodity_key PK, commodity_code UQ, commodity_name, commodity_group, base_unit, default_currency, notes)
dim_region(region_key PK, region_code UQ, region_name, country)
dim_data_source(data_source_key PK, source_code UQ, name, url, access, license)
dim_market_instrument(market_instrument_key PK, commodity_key FK, instrument_code, ...)  -- UNIQUE(commodity_key, instrument_code)
commodity_region_map(map_id PK, commodity_key FK, region_key FK, role, label)            -- UNIQUE(commodity_key, region_key, role)
commodity_profile_registry(registry_id PK, commodity_key FK UQ, commodity_code UQ,
                           source_path, checksum, version, profile JSONB)                -- full profile + sha256

-- One fact table per domain. Every fact is point-in-time correct:
--   <obs/period/event>_date = the date the value DESCRIBES
--   release_date            = when the value first became KNOWABLE  (CHECK release_date >= <date>)
--   revision                = append-only counter for revised series
fact_price_daily(price_id PK, commodity_key FK, market_instrument_key FK NULL, data_source_key FK NULL,
                 price_date, open, high, low, close, settle, volume, open_interest, currency, release_date, ...)
fact_weather_daily(weather_id PK, commodity_key FK, region_key FK, data_source_key FK NULL,
                   weather_date, metric_code, release_date, ...)
fact_macro_daily(macro_id PK, commodity_key FK NULL, data_source_key FK NULL,
                 macro_date, indicator_code, release_date, ...)
fact_logistics_periodic(logistics_id PK, commodity_key FK NULL, region_key FK NULL, data_source_key FK NULL,
                        period_start, period_end, indicator_code, release_date, ...)  -- CHECK period_end >= period_start
fact_supply_demand_periodic(sd_id PK, commodity_key FK, region_key FK NULL, data_source_key FK NULL,
                            period_start, period_end, metric_code, release_date, ...)  -- CHECK period_end >= period_start
fact_event_risk(event_id PK, commodity_key FK NULL, region_key FK NULL, data_source_key FK NULL,
                event_date, metric_code, category, release_date, ...)

-- Each fact: a release_date btree index + a NULL-safe COALESCE grain unique index, e.g.:
CREATE INDEX ix_fact_price_daily_release_date ON fact_price_daily (release_date);
CREATE UNIQUE INDEX uq_fact_price_daily_grain ON fact_price_daily
    (commodity_key, COALESCE(market_instrument_key,-1), price_date, revision);
-- (analogous indexes exist for weather, macro, logistics, supply_demand, event_risk)
```

`commodity_key`/`region_key` are nullable on `fact_macro_daily`,
`fact_logistics_periodic`, and `fact_event_risk` because those indicators (FX, freight
indices, geopolitical shocks) are often shared/global rather than owned by one
commodity. `commodity_region_map` carries the per-commodity region **role**
(production/consumption/export/import/weather). The **profile registry** stores each
parsed YAML profile verbatim (JSONB) plus a SHA-256 checksum so the loader is idempotent
and can detect changes (version bump).

The two **periodic** fact tables use an explicit period range — `period_start` +
`period_end` (with `CHECK (period_end >= period_start)`) — rather than a single
reference date, so weekly/monthly/quarterly/marketing-year/crop-report series are
unambiguous, and `release_date >= period_end` keeps them point-in-time correct.
For these delayed/revised series, `release_date` (the as-of date) and `data_source_key`
are part of the **unique grain**, so the same period from a different vintage or source
is a distinct row — e.g. logistics grain =
`(COALESCE(commodity_key,-1), COALESCE(region_key,-1), data_source_key, indicator_code,
period_start, period_end, release_date, revision)`.

On the periodic facts, `data_source_key` is **NOT NULL** (FK `ON DELETE RESTRICT`):
every periodic fact must carry source lineage and is therefore audit-safe and
deterministically unique. Data with no external provider still maps to a
`dim_data_source` row (e.g. `manual`, `internal`, `unknown`) — never a NULL source.

### 3.2 Handling look-ahead bias (point-in-time correctness)

Look-ahead bias is the #1 way a commodity backtest lies to you. The schema defends
against it on three fronts:

1. **Two dates per row.** `obs_date` is the date a value describes; `release_date`
   is when that value first became *knowable*. A feature for date *T* may only read
   rows where `release_date <= T`. USDA WASDE, export stats, and weather reanalysis are
   all published with a lag — `release_date` encodes that lag. A `CHECK (release_date
   >= obs_date)` constraint enforces the ordering at the database level.
2. **Revisions are append-only.** Revised macro series get a new row with an
   incremented `revision` and a later `release_date`; we never UPDATE a published value.
   Backtests reconstruct "what was known at time T" by selecting the latest revision
   with `release_date <= T`. The check + COALESCE grain index apply to **every** fact
   table, so the guarantee holds uniformly across price/weather/macro/logistics/S&D.
3. **Point-in-time materialized views.** `db/views/` will hold ML-facing
   materialized views that join the fact tables *as-of* a snapshot date, so feature
   builders physically cannot see future or future-revised data.

### 3.3 Materialized views for ML

ML reads **materialized views**, never raw fact tables, so feature definitions are
centralized, reproducible, and point-in-time safe. Việc triển khai được chia làm 2 lớp:
1. **Canonical PIT Long View (`v_ml_daily_feature_events_long`)**: Lớp chuẩn hóa kết hợp lưới thời gian (Time Grid) theo coverage window của từng commodity với các Fact tables (Price, Weather, Macro, v.v.). View này áp dụng quy tắc chống Look-ahead bias: `observation_date <= as_of_date` VÀ `release_date <= as_of_date`. Dữ liệu sau đó được gom thành mảng JSONB trong `v_ml_daily_features_jsonb`.
2. **Wide Materialized View (`mv_ml_daily_features_wide`)**: Artifact được sinh ra bằng Python compiler (`db/views/compile_ml_feature_views.py`) từ cấu hình YAML để phục vụ trực tiếp cho ML. Script này tự động extract các cột wide format mà không cần viết tay SQL (chống hardcode). Mọi query ML sẽ query view này. Dữ liệu được làm mới qua `REFRESH MATERIALIZED VIEW CONCURRENTLY`.

### 3.4 ETL foundation (Phase 3A — dry-run skeleton)

> **Implemented in Phase 3A.** Source = `etl/` + `db/seeds/seed_data_sources.py`.
> No external ingestion, no network, no credentials, no fact writes yet.

The `etl/` package is a generic, safe skeleton:

- **`etl/contracts.py`** — `FactFamily` (the 6 families, 1:1 with the fact tables),
  `FACT_FAMILIES` specs (target table, periodic?, code field, required dims), and the
  source-agnostic `NormalizedRecord` (carries business *codes*, not surrogate keys).
- **`etl/validation.py`** — structured validation returning typed `ErrorCode`s
  (`MISSING_SOURCE`, `MISSING_RELEASE_DATE`, `INVALID_PERIOD_RANGE`, `UNKNOWN_TARGET_FACT`,
  `MISSING_COMMODITY/REGION/INSTRUMENT/METRIC`, `LOOKAHEAD_UNSAFE`). It never sanitizes
  or fails open. Source lineage (`data_source_code`) and `release_date` are required for
  **every** fact; periodic facts require `period_start`/`period_end` with `period_end >=
  period_start`; `release_date >= reference_date` enforces look-ahead safety.
- **`etl/mapping.py`** — `dry_run()` validates, normalizes, and builds the target
  fact-table payload, returning a report. It takes **no DB session and inserts nothing**
  (`DryRunReport.inserted` is always 0). Code→surrogate-key resolution is a later phase.
- **`etl/sources/<family>/`** — stub `BaseSource` adapters (market/weather/macro/
  logistics/supply_demand/events) that declare their family and `collect()` no records.
- **`db/seeds/seed_data_sources.py`** — idempotent, additive seed of baseline
  `dim_data_source` rows (`manual`, `internal`, `unknown`, `seed_profile`) so periodic
  facts (which require non-null `data_source_key`) always have source lineage available.

**Phase 3B — reference resolution + insert planning (still no persisted writes):**

- **`etl/resolution.py`** — `ReferenceResolver` (read-only) maps business codes to
  surrogate keys against the live dimensions (`commodity_code→commodity_key`,
  `region_code→region_key`, `instrument_code→market_instrument_key` per-commodity,
  `data_source_code→data_source_key`); a present-but-unknown code yields a typed error
  (`UNKNOWN_COMMODITY/REGION/INSTRUMENT/SOURCE`). It never creates missing dimensions.
- **`etl/conflicts.py`** — per-family unique-grain definitions (mirroring the COALESCE
  indexes) and a NULL-safe `conflict_exists()` pre-check.
- **`etl/planner.py`** — `InsertPlanner.plan()` validates → resolves → builds the
  resolved (surrogate-key) payload → pre-checks grain conflict → returns an
  `InsertPlan` (`target_table`, resolved keys, payload, grain fields, errors,
  `conflict`, `would_insert`). It is **plan-only** (SELECT-only, no writes).
  `simulate_and_rollback()` inserts the would-insert plans inside a SAVEPOINT and rolls
  back, proving the rows are insertable while leaving persisted fact counts unchanged.

**Phase 3C — controlled fixture connectors + batch report (still dry-run only):**

- **`etl/sources/fixture.py`** — `FixtureSource(BaseSource)` reads tiny LOCAL JSON
  fixtures under `etl/fixtures/` and yields `NormalizedRecord`s. Sandboxed: the
  resolved path must stay inside the fixture root (rejects `..` traversal / absolute
  escapes), only `.json` (or `.yaml` via `yaml.safe_load`) is accepted, malformed JSON
  raises `FixtureError`. No network, no writes.
- **`NormalizedRecord.from_dict()`** — parses ISO date strings; unknown input keys are
  not silently lost (recorded → `IGNORED_FIELD` warning); a malformed date becomes an
  `INVALID_DATE` error. No eval, no I/O.
- **`etl/fixtures/<family>.json`** — tiny deterministic fixtures for all six families,
  with both valid and invalid rows (unknown source/region/instrument/commodity, missing
  release_date, reversed period) across ≥2 commodities.
- **`etl/report.py`** — `plan_batch(session, records, *, source_code, simulate)` runs the
  planner over a batch (one resolver per batch → batch-scoped cache) and returns a
  deterministic `BatchPlanReport` (`totals`, `by_family`, `by_target`, `by_error_code`,
  `by_warning_code`, `items`). `to_dict()` is JSON-safe and **leak-safe** — metadata only,
  never raw payload values or resolved keys. `simulate=True` attaches the rollback proof.
- Daily-fact conflict pre-checks (price/weather/macro/event_risk) are hardened with a
  NULL-safe SQLite matrix plus an env-gated (`CQP_TEST_PG_URL`) PostgreSQL variant.

---

## 4. Core domain models

- **DimCommodity** — what we forecast; carries `commodity_group`, `base_unit`, `default_currency`.
- **DimMarketInstrument** — a tradable/market series scoped to a commodity (futures, spot index).
- **DimRegion** — a geography (production / consumption / export / import / weather area).
- **DimDataSource** — provenance and license/access metadata for every series.
- **CommodityRegionMap** — maps a commodity to a region with a role (the per-commodity context).
- **CommodityProfileRegistry** — each commodity's parsed YAML profile (JSONB) + checksum/version.
- **Fact tables** — point-in-time observations by domain: `fact_price_daily`,
  `fact_weather_daily`, `fact_macro_daily`, `fact_logistics_periodic`,
  `fact_supply_demand_periodic`, `fact_event_risk`. Metric/indicator identified by a `*_code` column.
- **Driver** — a named input signal (physical / macro / logistics / event-risk) declared
  in the profile; resolved to a fact table + `metric_code`/`indicator_code` by the ETL phase.
- **Model** — a forecasting configuration (family + horizon + features) recorded in `ml/registry/`.

---

## 5. Ten-phase roadmap

| Phase | Name                          | Outcome                                                                 |
| ----- | ----------------------------- | ----------------------------------------------------------------------- |
| 1     | Foundation Initialization     | Monorepo tree, docs, configs, 16 commodity YAML profiles. *(done)*        |
| 2     | Data Contracts & Schema       | Star schema (dims + 6 facts + registry), Alembic, raw SQL mirror, loader. *(done)* |
| **3A**| **ETL Foundation**            | `etl/` contracts + validation + dry-run mapping + stub sources; source-registry seed. *(this phase)* |
| 3B    | ETL Source Adapters           | Real `etl/sources/*` connectors (market, weather, macro, logistics, S&D, events).|
| 4     | Loaders & Point-in-Time Store | `etl/loaders/*` resolve codes→keys and insert into the fact tables; enforce `release_date`. |
| 5     | Materialized Views & Features | `db/views/*` panels; `ml/features/*` Fourier + lag/rolling features.     |
| 6     | Model Layer                   | `ml/models/*` (statsmodels, sklearn, xgboost, prophet) behind one API.   |
| 7     | Backtesting & Registry        | `ml/backtests/*` walk-forward; `ml/registry/*` versioned model metadata. |
| 8     | API Service                   | FastAPI endpoints for commodities, series, forecasts, backtests.         |
| 9     | Web Frontend                  | Next.js + Plotly/ECharts dashboards for forecasts and drivers.           |
| 10    | Productionization             | CI/CD, Docker images, deployment, monitoring, data-quality gates.        |

---

## 6. Repository layout

```
apps/   api (FastAPI) + web (Next.js)
db/     migrations, views, seeds, commodity_profiles
etl/    sources/{market,weather,macro,logistics,supply_demand,events}, loaders, tests
ml/     features, models, backtests, registry, tests
configs/commodities  16 YAML commodity profiles (source of truth)
data/   raw, processed, exports (gitignored content)
infra/  docker, github-actions, deployment
tests/  integration, quality
```

See `README.md` for setup and `CLAUDE.md` for the operating rules every agent session
must follow.
