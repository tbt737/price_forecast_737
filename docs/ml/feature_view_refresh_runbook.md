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

## Canonicalize production TABLE → MATERIALIZED VIEW (two-phase)

**Owner approval required.** Sole apply path:

```bash
# From the approved fixed commit SHA only:
python scripts/canonicalize_ml_feature_mv.py --write
```

### Why two-phase

A single transaction that renames the production TABLE and then runs a long
`REFRESH MATERIALIZED VIEW` holds `AccessExclusiveLock` for the entire rebuild.
On small Supabase plans that can strand a session (client timeout / pooler) while
the backend keeps the lock. The two-phase runner **never refreshes inside the
cutover transaction**.

### Sequence

1. **Fail-closed precheck** — refuse if `mv_ml_daily_features_wide_cand` or
   `mv_ml_daily_features_wide_table_bak` (or their index names) already exist.
2. **Build candidate** (production TABLE name untouched):
   - `CREATE MATERIALIZED VIEW …_cand … WITH NO DATA`
   - unique index `uq_mv_ml_daily_features_wide_cand`
   - `REVOKE` PUBLIC/anon/authenticated
   - blocking `REFRESH` with finite `statement_timeout` (`15min`, never `0`)
3. **Parity on candidate** (`relkind=m`, populated, unique index valid, no dup grain).
4. **Fact snapshot** of `fact_price_daily` (row count / max revision / max date / hash).
5. **Final `REFRESH MATERIALIZED VIEW CONCURRENTLY`** on candidate (same finite timeout).
6. **Re-check fact snapshot** — refuse cutover if facts changed during final refresh.
7. **Short cutover transaction** (`lock_timeout=3s`, `statement_timeout=15s`,
   session `pg_advisory_lock` for cutover only):
   - re-check fact snapshot inside the txn
   - `TABLE mv_ml_daily_features_wide` → `…_table_bak` (+ rename unique index)
   - candidate MV → `mv_ml_daily_features_wide` (+ rename unique index)
   - `REVOKE` on MV + backup
   - **no REFRESH in this transaction**

Candidate build failure cleans up the orphan candidate and **does not** touch the
canonical TABLE. Cutover failure rolls back the short txn; use the flags below.

Dry-run (no DDL):

```bash
python scripts/canonicalize_ml_feature_mv.py
```

Post-cutover rollback (restores TABLE from backup; does **not** auto-drop backup
as a separate cleanup step — rename consumes the backup name):

```bash
python scripts/canonicalize_ml_feature_mv.py --rollback
```

Orphan candidate cleanup (never drops backup):

```bash
python scripts/canonicalize_ml_feature_mv.py --cleanup-candidate
```

### Manual SQL fragments (reference only)

`db/migrations/005_mv_ml_canonicalize_preamble.sql` / `_rollback.sql` document
shapes; production must use the Python runner, not multi-file psql.

---

## Parity criteria (must pass before declaring apply done)

Record **before** cutover (on candidate) and **after** cutover (on canonical name):

| Check | Pass rule |
|---|---|
| `relkind` | `m` for `mv_ml_daily_features_wide` |
| `relispopulated` | `true` |
| Unique index | `uq_mv_ml_daily_features_wide` exists, unique, **valid** |
| Refresh gate | `python scripts/refresh_ml_features.py --write` → exit 0, log `refreshed …` |
| Grain | `COUNT(*) = COUNT(DISTINCT (commodity_key, as_of_date))` |
| Coverage | `COUNT(DISTINCT commodity_key)` ≥ pre-migration non-equity commodities that have prices (document number) |
| Freshness | `MAX(as_of_date)` ≥ previous table max (or justify gap if SQL view is PIT-stricter) |
| Latest-revision | Spot-check one restated-capable series: wide `price_close` matches `load_price_series` / API latest-revision close |
| PIT | No `release_date > as_of_date` leakage for a held-out weather/macro fixture (integration test) |
| Forecast consumers | `ml.forecast` / `ml.runner` SELECT against MV succeeds for a known commodity_key; API forecast smoke for one code |
| Offline builder | `ml/build_pandas_mv.py` writes only `offline_ml_daily_features_wide_pandas`; production name untouched |
| Fact race gate | `fact_snapshot` unchanged between final concurrent refresh and cutover |

**Note:** Column set will jump from the narrow pandas table (~11 cols) to the compiled wide MV (~200+ metric columns). Row counts will differ (SQL path is event/PIT shaped, not a full calendar ffill grid). Parity is **semantic** (grain, revision, PIT, freshness floor), not byte-identical to the backup table.

---

## When YAML metrics change

1. `python db/views/compile_ml_feature_views.py`  
2. `DROP MATERIALIZED VIEW mv_ml_daily_features_wide;`  
3. Re-apply `010` + `011`  
4. Initial `REFRESH` (non-concurrent) once, then CONCURRENTLY thereafter  
