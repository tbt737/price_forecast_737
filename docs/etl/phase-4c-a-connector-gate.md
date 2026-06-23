# Phase 4C-A — Connector provenance gate (DB stays nullable)

Enforces source provenance **at the connector/ETL boundary** — where a connector /
mock fixture / raw payload becomes a `NormalizedRecord` — while leaving the database
columns **nullable**. This is the fail-closed half of the provenance story; the
required/`NOT NULL` migration is deferred to **Phase 4C-B**.

## Why the boundary, not the writer
`validate_record()` (used by the planner/writer) is **unchanged**. Adding a global
provenance requirement there would reject legacy/direct records and break Phase 4A/4B
behaviour. Instead the gate lives in `etl/provenance.py` and is applied by the
connector layer (`BaseSource.gate()`), so:

- **connector-originated** records must carry provenance before reaching the writer;
- **legacy/direct** records (hand-built, no connector) keep Phase 4A/4B semantics.

## The gate (`etl/provenance.py`)
`gate_record(record)` returns blocking issues (empty = accepted); `gate_records(...)`
partitions a batch into `accepted` / `rejected` (`ConnectorGateReport`).

| Condition | Error code |
| --- | --- |
| missing `data_source_code` | `MISSING_SOURCE` |
| missing `source_record_id` | `MISSING_SOURCE_RECORD_ID` |
| missing `source_payload_hash` | `MISSING_SOURCE_PAYLOAD_HASH` |
| `source_payload_hash` not a 64-char lowercase sha256 hex | `INVALID_SOURCE_PAYLOAD_HASH` |

It never fabricates provenance to pass itself.

## Deterministic provenance
- **`canonical_payload_hash(payload)`** — SHA-256 hex of canonical JSON: `sort_keys`
  (key-order independent), tight separators, UTF-8, `default=str`. Provenance metadata
  fields are excluded, so attaching provenance never changes the data hash. No volatile
  fields (timestamps, random ids, object `repr`).
- **`make_source_record_id(source_code, *parts)`** — stable `"<source_code>:<part>:…"`.
  Never a random UUID, never a local DB id.
- **`attach_provenance(record, payload, …)`** — fills missing provenance only; honours
  any id/hash the source already supplied.

## Connector contract
`FixtureSource.collect()` now emits, for every row, a deterministic
`source_record_id = "<data_source_code>:<fixture-stem>:<row-index>"` and
`source_payload_hash = canonical_payload_hash(raw row)`. Stable run-to-run; re-ingesting
the same source record replays as **idempotent** through the Phase 4B writer.

## Out of scope (kept untouched)
DB columns stay nullable — no `NOT NULL`, no migration `003`, no change to
`002_provenance.sql`, no unique-grain/index change, no backfill, no real external
ingestion. Writer/replay semantics from Phase 4A/4B are preserved.

## Deferred to Phase 4C-B
Backfill historical rows → verify zero NULLs → guarded `NOT NULL` migration with
rollback, only after a stable real connector guarantees `source_record_id`.
