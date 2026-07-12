"""Refresh the ML wide materialized view after ingest (ops helper).

Canonical artifact: PostgreSQL MATERIALIZED VIEW ``mv_ml_daily_features_wide``
(see ARCHITECTURE.md / db/views). Dry-run by default (INV-7); pass ``--write``.

Exit codes:
  0 — refreshed, or skipped because the matview is missing (not yet applied)
  1 — CONTRACT_VIOLATION (wrong relkind / missing unique index) or refresh error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

_API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

MV_NAME = "mv_ml_daily_features_wide"
UNIQUE_INDEX = "uq_mv_ml_daily_features_wide"

RelationStatus = Literal["missing", "matview_ready", "matview_no_unique", "wrong_kind"]


def classify_mv_relation(session: Session, *, schema: str = "public") -> tuple[RelationStatus, str]:
    """Return (status, detail) for the production ML feature relation.

    ``to_regclass`` alone is insufficient: a pandas-built TABLE shares the name and
    would pass a naive existence check, then fail REFRESH MATERIALIZED VIEW.
    """
    row = session.execute(
        text(
            """
            SELECT c.relkind
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relname = :name
            """
        ),
        {"schema": schema, "name": MV_NAME},
    ).scalar_one_or_none()
    if row is None:
        return "missing", f"{schema}.{MV_NAME} does not exist"
    if row != "m":
        kind = {"r": "table", "v": "view"}.get(row, row)
        return (
            "wrong_kind",
            f"CONTRACT_VIOLATION: {schema}.{MV_NAME} is a {kind} (relkind={row}), "
            f"expected materialized view — refuse REFRESH",
        )
    has_unique = session.execute(
        text(
            """
            SELECT EXISTS (
              SELECT 1
              FROM pg_class t
              JOIN pg_namespace n ON n.oid = t.relnamespace
              JOIN pg_index ix ON ix.indrelid = t.oid
              JOIN pg_class i ON i.oid = ix.indexrelid
              WHERE n.nspname = :schema
                AND t.relname = :name
                AND i.relname = :idx
                AND ix.indisunique
            )
            """
        ),
        {"schema": schema, "name": MV_NAME, "idx": UNIQUE_INDEX},
    ).scalar()
    if not has_unique:
        return (
            "matview_no_unique",
            f"CONTRACT_VIOLATION: matview {MV_NAME} exists but unique index "
            f"{UNIQUE_INDEX} is missing — CONCURRENTLY refresh refused",
        )
    return "matview_ready", f"{schema}.{MV_NAME} ready for CONCURRENTLY refresh"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="execute REFRESH against DATABASE_URL (default is dry-run)",
    )
    args = parser.parse_args(argv)

    if not args.write:
        print(
            f"DRY-RUN: would classify {MV_NAME} then "
            f"REFRESH MATERIALIZED VIEW CONCURRENTLY {MV_NAME} "
            f"(skip if missing; exit 1 on CONTRACT_VIOLATION)"
        )
        return 0

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    with session_factory() as session:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            print(f"skip: dialect {bind.dialect.name} has no materialized views")
            return 0

        status, detail = classify_mv_relation(session)
        if status == "missing":
            print(f"skip: {detail}")
            return 0
        if status in ("wrong_kind", "matview_no_unique"):
            print(detail)
            return 1

        session.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {MV_NAME}"))
        session.commit()
        print(f"refreshed {MV_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
