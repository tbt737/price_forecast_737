"""Bulk historical backfill — fast path for ingesting years of history.

The incremental ``write_batch`` does per-row DB round-trips (safe for daily
deltas); that is impractical for tens of thousands of rows over a remote DB.
This path resolves surrogate keys once (the resolver caches), builds payloads,
and bulk-inserts with ``ON CONFLICT DO NOTHING`` (idempotent at the unique grain).
Daily ingestion still uses the safe ``write_batch``.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

_API_DIR = Path(__file__).resolve().parent.parent / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from etl.conflicts import TARGET_MODELS  # noqa: E402
from etl.contracts import FactFamily  # noqa: E402
from etl.ingest import build_connectors  # noqa: E402
from etl.ingestion.config import load_ingestion_config  # noqa: E402
from etl.planner import build_payload  # noqa: E402
from etl.resolution import ReferenceResolver  # noqa: E402
from etl.sources.base import BaseSource  # noqa: E402
from etl.validation import validate_record  # noqa: E402


def _row_count(session: Session, model: Any) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _bulk_insert(session: Session, model: Any, rows: list[dict[str, Any]], chunk: int) -> None:
    """Chunked INSERT ... ON CONFLICT DO NOTHING (idempotent at the unique grain)."""
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _pg_insert

        make_insert: Any = _pg_insert
    else:  # sqlite (tests) supports the same on_conflict_do_nothing
        from sqlalchemy.dialects.sqlite import insert as _sqlite_insert

        make_insert = _sqlite_insert

    for start in range(0, len(rows), chunk):
        stmt = make_insert(model).values(rows[start : start + chunk]).on_conflict_do_nothing()
        session.execute(stmt)


def backfill(
    session: Session,
    *,
    connectors: list[BaseSource] | None = None,
    which: str = "all",
    period: str = "10y",
    weather_days: int = 1825,
    history_days: int = 400,
    chunk: int = 1000,
    today: date | None = None,
) -> dict[str, Any]:
    """Collect history from the connectors and bulk-insert it (idempotent)."""
    if connectors is None:
        config = load_ingestion_config()
        connectors = build_connectors(
            config, which=which, period=period, weather_days=weather_days,
            today=today or date.today(), history_days=history_days,
        )

    resolver = ReferenceResolver(session)
    by_family: dict[FactFamily, list[dict[str, Any]]] = defaultdict(list)
    collected = 0
    skipped_invalid = 0

    for connector in connectors:
        for record in connector.collect():
            collected += 1
            spec = record.spec()
            resolution = resolver.resolve(record)
            validation = validate_record(record)
            if spec is None or validation.errors or resolution.issues:
                skipped_invalid += 1
                continue
            by_family[record.family].append(build_payload(record, resolution, spec))

    inserted: dict[str, int] = {}
    for family, rows in by_family.items():
        model = TARGET_MODELS[family]
        before = _row_count(session, model)
        _bulk_insert(session, model, rows, chunk)
        session.flush()
        inserted[family.value] = _row_count(session, model) - before  # accurate; rowcount is unreliable for ON CONFLICT
    session.commit()

    return {
        "collected": collected,
        "skipped_invalid": skipped_invalid,
        "inserted": inserted,
        "inserted_total": sum(inserted.values()),
    }
