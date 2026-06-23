# Phase 4B — Source provenance & replay contract

Adds **optional** source provenance to facts and a provenance-aware replay path in
`etl/writer.py`. Still fixture/mock only — no external ingestion. **No NOT NULL
provenance, no grain/index change** (required provenance is Phase 4C).

## Schema (additive, nullable)
Every fact table gains two nullable columns (shared via `_FactMixin`):

| Column | Type | Notes |
| --- | --- | --- |
| `source_record_id` | `VARCHAR(200)` NULL | stable ID of the source record (when known) |
| `source_payload_hash` | `VARCHAR(64)` NULL | hash of the source payload (e.g. sha256 hex) |

- Alembic: `apps/api/app/migrations/versions/0002_add_source_provenance_columns.py`
  (upgrade `ADD COLUMN`, downgrade `DROP COLUMN`).
- Raw SQL mirror: `db/migrations/002_provenance.sql` (`ADD COLUMN IF NOT EXISTS`, no DROP).
- These columns are **not** part of any unique grain index.

## Writer semantics
Provenance is checked **first**, then grain (provenance never bypasses a grain conflict):

1. **Provenance identity** = `(target_table, data_source_key, source_record_id)` — used
   only when the record carries a `source_record_id` and a resolved source.
   - existing match, same value **and** same `source_payload_hash` → **idempotent** no-op.
   - existing match, different value or hash → **conflict** (`conflict_kind="provenance"`),
     no write.
   - `data_source_key` is part of the identity **even when it is not part of the fact's
     unique grain** (e.g. daily facts grain on commodity/instrument/date, not source).
     So the *same* `source_record_id` under a *different* data source is **not** read as a
     replay — it falls through to grain logic, where a same-grain/different-value row
     still raises a grain conflict. Provenance never bypasses a grain conflict.
2. **Grain identity** (Phase 4A, unchanged) — used when there is no provenance match.
   `source_record_id`/`source_payload_hash` are excluded from the grain value comparison,
   so records **without** provenance behave exactly as in Phase 4A.
   - same grain, same value → idempotent; same grain, different value → conflict
     (`conflict_kind="grain"`).

Dry-run still writes nothing; a batch with any reject/conflict still rolls back
entirely (atomic). `WriteReport.items` carry an optional `conflict_kind`
(`"provenance"` | `"grain"`) for conflicts.

## Deferred to Phase 4C
- Required/fail-closed provenance (NOT NULL), enforced once real connectors guarantee
  stable source IDs.
- Server-side hashing / raw-payload staging contract.
