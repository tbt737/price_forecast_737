# Phase 4A — ETL persistent write path

`etl/writer.py` turns Phase 3B/3C insert plans into a controlled DB write. Still
fixture/mock only — **no external ingestion, no new schema, no `source_record_id`
column.**

## API
`write_batch(session, records, *, dry_run=True) -> WriteReport`

- `dry_run=True` (default): resolve → plan → classify → report. **Writes nothing.**
- `dry_run=False`: classify, then **atomically** insert the NEW rows in a
  transaction and commit; otherwise roll back.

`canonical_identity(plan)` — deterministic identity = `(target_table, sorted grain
items)`. It mirrors the DB unique grain exactly (which already includes
`data_source_key` for periodic facts and the instrument/region/metric/date fields
per Phase 2), so two records collide here iff they collide in the database. No new
column is introduced.

## Per-record classification (vs the DB *and* the in-batch staged set)
| Outcome | Meaning | Write |
| --- | --- | --- |
| `rejected` | validation/resolution failed (incl. missing/unknown source) | none |
| `new` | no row for this identity | insert |
| `idempotent` | same identity **and** same normalized non-grain values exist | no-op |
| `conflict` | same identity but **different** normalized values | none |

Value comparison normalizes numerics to `Decimal` (Decimal/float/int safe) and
compares dates/strings directly — no careless string compares.

## Guarantees
- **Lineage fail-closed:** missing `data_source_code` → `MISSING_SOURCE`; unknown →
  `UNKNOWN_SOURCE`; both reject with no write. (Inherited from validation/resolution.)
- **Idempotent replay:** the same record+value never duplicates.
- **Conflict safety:** same grain with a different value never overwrites — it is a
  conflict and the batch does not write.
- **Atomic batch:** if **any** record is `rejected` or `conflict`, the whole batch
  rolls back — no partial fact rows.

`WriteReport.to_dict()`/`summary()` are deterministic and leak-safe (metadata +
counts + error codes only — no raw payload values or resolved keys).
