"""Read-only freshness / coverage gate for the daily ingest (config-driven).

Reads ``monitoring.groups`` from ``configs/ingestion/sources.yaml`` (no hardcoded ticker
list). A group is STALE when its latest price date is older than ``max_gap_days`` calendar
days. **Critical** groups (liquid futures) fail the gate → exit 1, so a green CI run means
market data actually advanced. **Non-critical** groups (scraped VN spot sources that can
die silently) are surfaced as a WARNING and only fail under ``--strict`` — so a dedicated
monitor can catch a dead PNJ/Phú Quý/VNAppMob endpoint without making the daily VN feed
blocking. Never writes; never prints the DB URL. ``is_within_gap`` is unit-tested.

Usage (reads DATABASE_URL from env/.env):
    python scripts/check_freshness.py            # daily gate: futures critical, VN warn
    python scripts/check_freshness.py --strict   # monitor: any stale group fails
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_DIR = _REPO_ROOT / "apps" / "api"
for _p in (_REPO_ROOT, _API_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def is_within_gap(latest: date | None, today: date, max_gap_days: int) -> bool:
    """Fresh iff ``latest`` exists and is at most ``max_gap_days`` calendar days before
    ``today``. A missing date (None) is always stale."""
    if latest is None:
        return False
    return (today - latest).days <= max_gap_days


def _latest_date(session, commodities: list[str]) -> date | None:
    from sqlalchemy import text

    return session.execute(
        text(
            "SELECT max(f.price_date) FROM fact_price_daily f "
            "JOIN dim_commodity co ON co.commodity_key = f.commodity_key "
            "WHERE co.commodity_code = ANY(:codes)"
        ),
        {"codes": list(commodities)},
    ).scalar()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Config-driven freshness/coverage gate.")
    parser.add_argument("--strict", action="store_true", help="also fail on stale non-critical groups")
    args = parser.parse_args(argv)

    from etl.ingestion.config import load_freshness_groups

    groups = load_freshness_groups()
    today = date.today()

    from app.db.session import get_session_factory

    session = get_session_factory()()
    should_fail = False
    warned = False
    try:
        for g in groups:
            latest = _latest_date(session, list(g.commodities))
            tag = "critical" if g.critical else "non-critical"
            if is_within_gap(latest, today, g.max_gap_days):
                print(f"[freshness] OK — {g.name} ({tag}): latest {latest} within {g.max_gap_days}d of {today}")
            else:
                print(
                    f"[freshness] STALE — {g.name} ({tag}): latest {latest} older than "
                    f"{g.max_gap_days}d before {today}",
                    file=sys.stderr,
                )
                if g.critical or args.strict:
                    should_fail = True
                else:
                    warned = True
    finally:
        session.close()

    if should_fail:
        return 1
    if warned:
        print("[freshness] non-critical group(s) stale — warning only (use --strict to fail).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
