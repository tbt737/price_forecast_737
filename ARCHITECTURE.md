# ARCHITECTURE — Multi-Commodity Quant Forecasting Platform

> **Status:** Phase 1 (Foundation Initialization) complete. No business logic, API
> endpoints, ML training code, or frontend UI is implemented yet — only the
> configuration-driven skeleton and contracts described here.

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

### 3.1 Normalized schema (target — implemented in Phase 3)

Reference dimensions, then one tall fact table of observations:

```
commodity(commodity_id PK, commodity_code, commodity_name, commodity_group, base_unit, default_currency)
region(region_id PK, region_code, region_name, country, role)        -- role: production|consumption|export|import|weather
instrument(instrument_id PK, commodity_id FK, instrument_code, exchange, symbol, contract_unit, currency)
metric(metric_code PK, description, unit, frequency)                  -- e.g. spot_price, rainfall_mm, open_interest
data_source(source_id PK, source_code, name, url, license, access)   -- e.g. ICE, USDA, NASA_POWER, Drewry

-- Tall, generic fact table — works for every commodity/metric:
observation(
    observation_id PK,
    commodity_id FK,
    instrument_id FK NULL,        -- nullable: weather/macro rows need no instrument
    region_id FK NULL,
    metric_code FK,
    source_id FK,
    obs_date DATE,                -- the date the value REFERS to
    value NUMERIC,
    unit TEXT,
    ingested_at TIMESTAMPTZ,      -- when WE first stored it
    valid_from TIMESTAMPTZ,       -- when the source first PUBLISHED it (point-in-time)
    revision INT DEFAULT 0,       -- supports revised macro/USDA series
    UNIQUE(commodity_id, metric_code, region_id, instrument_id, obs_date, revision)
)
```

The tall `observation` table is the heart of the "never hardcode" rule: adding a new
metric never changes the schema — it is just new rows with a new `metric_code`.

### 3.2 Handling look-ahead bias (point-in-time correctness)

Look-ahead bias is the #1 way a commodity backtest lies to you. The schema defends
against it on three fronts:

1. **Two timestamps per row.** `obs_date` is the date a value describes; `valid_from`
   is when that value first became *knowable*. A feature for date *T* may only read
   rows where `valid_from <= T`. USDA WASDE, export stats, and weather reanalysis are
   all published with a lag — `valid_from` encodes that lag.
2. **Revisions are append-only.** Revised macro series get a new row with an
   incremented `revision` and a later `valid_from`; we never UPDATE a published value.
   Backtests reconstruct "what was known at time T" by selecting the latest revision
   with `valid_from <= T`.
3. **Point-in-time materialized views.** `db/views/` will hold ML-facing
   materialized views that join observations *as-of* a snapshot date, so feature
   builders physically cannot see future or future-revised data.

### 3.3 Materialized views for ML

ML reads **materialized views**, never raw tables, so feature definitions are
centralized, reproducible, and point-in-time safe. Planned views live in `db/views/`:
wide per-commodity panels (one row per `obs_date`, columns per `metric_code`),
as-of join views, and resampled (daily/weekly) frames for Fourier + ML pipelines.

---

## 4. Core domain models

- **Commodity** — what we forecast; carries `commodity_group`, `base_unit`, `default_currency`.
- **Instrument** — a tradable/market series tied to a commodity (futures, spot index).
- **Region** — a geography with a `role` (production / consumption / export / import / weather).
- **Metric** — a measured quantity identified by `metric_code` with a unit + frequency.
- **DataSource** — provenance and license/access metadata for every series.
- **Observation** — one point-in-time fact: (commodity, metric, region?, instrument?, date, value).
- **Driver** — a named, grouped input signal (physical / macro / logistics / event-risk)
  declared in the profile and resolved to one or more metrics.
- **Model** — a forecasting configuration (family + horizon + features) recorded in `ml/registry/`.

---

## 5. Ten-phase roadmap

| Phase | Name                          | Outcome                                                                 |
| ----- | ----------------------------- | ----------------------------------------------------------------------- |
| **1** | **Foundation Initialization** | Monorepo tree, docs, configs, 16 commodity YAML profiles. *(this phase)* |
| 2     | Data Contracts & Schema       | SQL migrations for normalized schema; Pydantic/SQLAlchemy domain models. |
| 3     | ETL Source Adapters           | `etl/sources/*` fetchers (market, weather, macro, logistics, S&D, events).|
| 4     | Loaders & Point-in-Time Store | `etl/loaders/*` normalize into `observation`; enforce `valid_from`.      |
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
