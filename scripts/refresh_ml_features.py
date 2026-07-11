"""Refresh the ML wide materialized view after ingest (ops helper).

Idempotent and safe to run when the view is missing (exits 0 with a skip message).
Uses CONCURRENTLY when PostgreSQL supports it so readers are not blocked.
Dry-run by default (INV-7); pass ``--write`` to execute.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import text  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="execute REFRESH against DATABASE_URL (default is dry-run)",
    )
    args = parser.parse_args(argv)

    if not args.write:
        print("DRY-RUN: would REFRESH MATERIALIZED VIEW CONCURRENTLY mv_ml_daily_features_wide")
        return 0

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    with session_factory() as session:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            print(f"skip: dialect {bind.dialect.name} has no materialized views")
            return 0
        exists = session.execute(
            text("SELECT to_regclass('public.mv_ml_daily_features_wide') IS NOT NULL")
        ).scalar()
        if not exists:
            print("skip: mv_ml_daily_features_wide does not exist yet")
            return 0
        # CONCURRENTLY requires a unique index (011_indexes_ml_feature_views.sql).
        session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_ml_daily_features_wide"))
        session.commit()
        print("refreshed mv_ml_daily_features_wide")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
