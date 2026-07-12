# Feature View Refresh Runbook (Phase 5C) + Canonicalize (direction A)

## Canonical ownership

| Artifact | Owner | Refresh |
|---|---|---|
| `mv_ml_daily_features_wide` | SQL compiler (`db/views/generated/010_*.sql`) + `011_indexes_*.sql` | `scripts/refresh_ml_features.py --write` → `REFRESH MATERIALIZED VIEW CONCURRENTLY` |
| `offline_ml_daily_features_wide_pandas` | `ml/build_pandas_mv.py` (offline / lab only) | N/A — never production |

`CREATE MATERIALIZED VIEW IF NOT EXISTS` **does not** replace an ordinary TABLE of the
same name. Production currently drifted to a pandas TABLE; that is why the ingest
refresh step failed with `is not a materialized view`.

---

## Daily refresh (after canonicalize)

Prerequisite: unique index `uq_mv_ml_daily_features_wide (commodity_key, as_of_date)`.

```bash
python scripts/refresh_ml_features.py --write
```

Gate behaviour:

| Catalog state | Action | Exit |
|---|---|---|
| missing | skip | 0 |
| `relkind=m` + unique index | `REFRESH … CONCURRENTLY` | 0 |
| any other relkind / matview without unique index | `CONTRACT_VIOLATION` | 1 |

---

## Canonicalize production TABLE → MATERIALIZED VIEW

**Owner approval required.** Sole apply path:

```bash
# From the approved fixed commit SHA only:
python scripts/canonicalize_ml_feature_mv.py --write
```

The runner holds ``pg_advisory_lock(hashtext('ml_feature_view_canonicalize'))``
for the **session** and runs rename → CREATE MV (WITH NO DATA, no IF NOT EXISTS) →
unique index → blocking REFRESH → REVOKE (MV + backup) inside **one transaction**.
Failure aborts the transaction (auto-rollback). Do **not** stitch loose SQL files
in separate psql sessions — an ``xact`` lock in the preamble file alone does not
cover later steps.

Dry-run (no DDL):

```bash
python scripts/canonicalize_ml_feature_mv.py
```

### Manual SQL fragments (reference only)

`db/migrations/005_mv_ml_canonicalize_preamble.sql` / `_rollback.sql` document the
rename/rollback shape; production must not rely on them as a multi-file procedure.

---

## Parity criteria (must pass before declaring apply done)

Record **before** preamble and **after** initial refresh:

| Check | Pass rule |
|---|---|
| `relkind` | `m` for `mv_ml_daily_features_wide` |
| Unique index | `uq_mv_ml_daily_features_wide` exists and is unique |
| Refresh gate | `python scripts/refresh_ml_features.py --write` → exit 0, log `refreshed …` |
| Grain | `COUNT(*) = COUNT(DISTINCT (commodity_key, as_of_date))` |
| Coverage | `COUNT(DISTINCT commodity_key)` ≥ pre-migration non-equity commodities that have prices (document number) |
| Freshness | `MAX(as_of_date)` ≥ previous table max (or justify gap if SQL view is PIT-stricter) |
| Latest-revision | Spot-check one restated-capable series: wide `price_close` matches `load_price_series` / API latest-revision close |
| PIT | No `release_date > as_of_date` leakage for a held-out weather/macro fixture (integration test) |
| Forecast consumers | `ml.forecast` / `ml.runner` SELECT against MV succeeds for a known commodity_key; API forecast smoke for one code |
| Offline builder | `ml/build_pandas_mv.py` writes only `offline_ml_daily_features_wide_pandas`; production name untouched |

**Note:** Column set will jump from the narrow pandas table (~11 cols) to the compiled wide MV (~200+ metric columns). Row counts will differ (SQL path is event/PIT shaped, not a full calendar ffill grid). Parity is **semantic** (grain, revision, PIT, freshness floor), not byte-identical to the backup table.

---

## When YAML metrics change

1. `python db/views/compile_ml_feature_views.py`  
2. `DROP MATERIALIZED VIEW mv_ml_daily_features_wide;`  
3. Re-apply `010` + `011`  
4. Initial `REFRESH` (non-concurrent) once, then CONCURRENTLY thereafter  
