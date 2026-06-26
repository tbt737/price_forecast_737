"""Apply compiled ML feature views to a database (dry-run by default)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import text
from app.db.session import get_session_factory

VIEW_FILES = (
    "001_v_ml_daily_feature_events_long.sql",
    "002_v_ml_daily_features_jsonb.sql",
    "generated/010_mv_ml_daily_features_wide.sql",
    "011_indexes_ml_feature_views.sql",
)


def _view_paths(views_dir: Path) -> list[Path]:
    return [views_dir / name for name in VIEW_FILES]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile and optionally apply ML feature views."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="execute SQL against the database (default is dry-run)",
    )
    args = parser.parse_args()

    import db.views.compile_ml_feature_views as compiler

    compiler.main()

    views_dir = Path(__file__).resolve().parent / "db" / "views"
    files = _view_paths(views_dir)

    if not args.apply:
        print("DRY-RUN: would apply the following ML feature view files:")
        for path in files:
            status = "found" if path.exists() else "MISSING"
            print(f"  [{status}] {path.relative_to(views_dir.parent.parent)}")
        print("Re-run with --apply to execute against the database.")
        return

    session_factory = get_session_factory()
    with session_factory() as session:
        for path in files:
            print(f"Executing {path.name}...")
            if not path.exists():
                print(f"Skipping missing file: {path}")
                continue
            sql = path.read_text(encoding="utf-8")
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            for stmt in statements:
                session.execute(text(stmt))
        session.commit()
        print("Successfully applied ML views to database.")


if __name__ == "__main__":
    main()
