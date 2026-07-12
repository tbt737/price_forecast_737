# Feature View Refresh Runbook (Phase 5C) + Two-phase canonicalize

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

## Canonicalize production TABLE → MATERIALIZED VIEW (two-phase + operator boundary)

**Owner approval required for each phase separately.** There is **no** one-shot
`--write` — production must stop after prepare for read-back, then approve cutover.

```bash
# Phase 1 — prepare only (canonical TABLE untouched):
python scripts/canonicalize_ml_feature_mv.py --prepare-candidate
# optional: --refresh-timeout-min 30   # bounded [5..120], default 30

# Phase 2 — only after explicit cutover approval + read-back of candidate:
python scripts/canonicalize_ml_feature_mv.py --cutover
```

### Why two commands

A single `--write` that builds then immediately renames removes the operator
boundary. Prepare must stop so production can inspect candidate parity before any
canonical rename. Heavy `REFRESH` never runs inside the cutover rename transaction
(avoids long `AccessExclusiveLock` on Micro plans / pooler disconnects).

### Prepare (`--prepare-candidate`)

1. Session `pg_advisory_lock`
2. Fail-closed if candidate/backup names (or indexes) already exist
3. `CREATE MATERIALIZED VIEW …_cand … WITH NO DATA` (canonical name untouched)
4. Unique index + `REVOKE` PUBLIC/anon/authenticated
5. Blocking `REFRESH` with finite timeout (default **30min**, never `0`)
6. Parity on candidate → **STOP** (status `prepared`)

On build failure: best-effort `--cleanup-candidate` semantics for the orphan;
canonical TABLE is never renamed.

### Cutover (`--cutover`)

1. Session `pg_advisory_lock`
2. Revalidate candidate — refuse if **missing**, **unpopulated**, **stale** (empty
   coverage), or **parity fail**
3. Full-fact fingerprint across **six** families:
   `fact_price_daily`, `fact_weather_daily`, `fact_macro_daily`,
   `fact_logistics_periodic`, `fact_supply_demand_periodic`, `fact_event_risk`
4. `REFRESH MATERIALIZED VIEW CONCURRENTLY` on candidate (same finite timeout)
5. Re-check full-fact fingerprint — refuse if changed
6. Short rename txn (`lock_timeout=3s`): TABLE→backup, candidate→canonical,
   rename indexes, `REVOKE` — **no REFRESH**

```bash
python scripts/canonicalize_ml_feature_mv.py --rollback
python scripts/canonicalize_ml_feature_mv.py --cleanup-candidate
```

Dry-run:

```bash
python scripts/canonicalize_ml_feature_mv.py
```

### Manual SQL fragments (reference only)

`db/migrations/005_mv_ml_canonicalize_preamble.sql` / `_rollback.sql` document
shapes; production must use the Python runner, not multi-file psql.

---

## Parity criteria (must pass before declaring apply done)

Record on **candidate** after prepare and again on **canonical** after cutover:

| Check | Pass rule |
|---|---|
| `relkind` | `m` |
| `relispopulated` | `true` |
| Unique index | exists, unique, **valid** |
| Refresh gate | `python scripts/refresh_ml_features.py --write` → exit 0 (post-cutover) |
| Grain | no duplicate `(commodity_key, as_of_date)` |
| Coverage | `COUNT(DISTINCT commodity_key)` ≥ pre-migration floor |
| Freshness | `MAX(as_of_date)` ≥ previous table max (or justify PIT gap) |
| Latest-revision | wide `price_close` matches canonical series / API |
| Forecast consumers | smoke against MV |
| Offline builder | only `offline_ml_daily_features_wide_pandas` |
| Fact race gate | 6-family fingerprint unchanged between final concurrent refresh and cutover |

**Note:** Column set jumps from the narrow pandas table (~11 cols) to the compiled
wide MV. Parity is semantic, not byte-identical to the backup table.

---

## When YAML metrics change

1. `python db/views/compile_ml_feature_views.py`  
2. `DROP MATERIALIZED VIEW mv_ml_daily_features_wide;`  
3. Re-apply `010` + `011`  
4. Initial `REFRESH` (non-concurrent) once, then CONCURRENTLY thereafter  
