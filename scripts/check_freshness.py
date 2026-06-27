"""Read-only freshness gate for the daily ingest.

Exits non-zero when the latest **futures** price date in the DB is staler than the
previous business day (weekend-aware), so a green CI run actually means market data
advanced — not that the job merely didn't crash. Never writes; never prints secrets
(no DB URL). Pure helpers (``previous_business_day`` / ``is_fresh``) are unit-tested.

Usage (reads DATABASE_URL from env/.env):
    python scripts/check_freshness.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

# The freshness query uses the ORM app package for the DB session factory.
_API_DIR = Path(__file__).resolve().parent.parent / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

# Liquid, daily-updating futures — the produce series are intentionally frozen and
# must not gate freshness.
FUTURES = ("GOLD", "CRUDE_OIL", "CORN", "WHEAT", "COPPER", "SUGAR", "SOYBEAN", "COCOA", "RICE")


def previous_business_day(d: date) -> date:
    """Most recent weekday strictly before ``d`` (skips Sat/Sun)."""
    cur = d - timedelta(days=1)
    while cur.weekday() >= 5:  # 5 = Sat, 6 = Sun
        cur -= timedelta(days=1)
    return cur


def is_fresh(latest: date | None, today: date) -> bool:
    """Fresh iff the latest futures date is at least the previous business day.

    A one-business-day grace avoids false alarms when *today's* close has not settled
    yet (the daily job runs before all markets finalise)."""
    if latest is None:
        return False
    return latest >= previous_business_day(today)


def _latest_futures_date(session) -> date | None:
    from sqlalchemy import text

    return session.execute(
        text(
            "SELECT max(f.price_date) FROM fact_price_daily f "
            "JOIN dim_commodity co ON co.commodity_key = f.commodity_key "
            "WHERE co.commodity_code = ANY(:codes)"
        ),
        {"codes": list(FUTURES)},
    ).scalar()


def main() -> int:
    from app.db.session import get_session_factory

    today = date.today()
    session = get_session_factory()()
    try:
        latest = _latest_futures_date(session)
    finally:
        session.close()

    expected = previous_business_day(today)
    if is_fresh(latest, today):
        print(f"[freshness] OK — latest futures {latest} >= expected {expected} (today {today})")
        return 0
    print(
        f"[freshness] STALE — latest futures {latest} < expected {expected} (today {today}); "
        "daily price ingest did not advance.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
