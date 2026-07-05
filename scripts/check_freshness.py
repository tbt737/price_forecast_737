"""Read-only freshness / coverage gate for the daily ingest (config-driven).

Reads ``monitoring.groups`` from ``configs/ingestion/sources.yaml`` (no hardcoded ticker
list). A group is STALE when its latest price date is older than ``max_gap_days`` calendar
days. **Critical** groups (liquid futures) fail the gate → exit 1, so a green CI run means
market data actually advanced. **Non-critical** groups (scraped VN spot sources that can
die silently) are surfaced as a WARNING and only fail under ``--strict`` — so a dedicated
monitor can catch a dead PNJ/Phú Quý/VNAppMob endpoint without making the daily VN feed
blocking. Never writes; never prints the DB URL. ``is_within_gap`` is unit-tested.

``--group`` scopes the check to named group(s) so a dedicated monitor can watch just the
VN sources without being coupled to the futures feed. An unknown ``--group`` name is a hard
error (exit 2) — a typo must never silently pass green.

Usage (reads DATABASE_URL from env/.env):
    python scripts/check_freshness.py                          # daily gate: futures critical, VN warn
    python scripts/check_freshness.py --strict                 # any stale group fails
    python scripts/check_freshness.py --group vn_domestic --strict  # VN-only monitor: VN stale ⇒ red
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


def select_groups(groups: list, names: list[str] | None) -> tuple[list, list[str]]:
    """Filter ``groups`` to the requested ``names`` (order-preserving). Returns
    ``(selected, unknown)`` where ``unknown`` is the requested names that match no group.
    ``names`` of None/empty selects every group (backward-compatible default)."""
    if not names:
        return list(groups), []
    wanted = list(dict.fromkeys(names))  # de-dupe, keep order
    configured = {g.name for g in groups}
    selected = [g for g in groups if g.name in set(wanted)]
    unknown = [n for n in wanted if n not in configured]
    return selected, unknown


def classify(group, latest: date | None, today: date, strict: bool) -> str:
    """Verdict for one group given its latest price date: ``'ok'`` | ``'warn'`` | ``'fail'``.
    A stale group fails when it is ``critical`` OR ``strict`` is set; otherwise it only warns."""
    if is_within_gap(latest, today, group.max_gap_days):
        return "ok"
    return "fail" if (group.critical or strict) else "warn"


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
    parser.add_argument(
        "--group",
        action="append",
        default=None,
        metavar="NAME",
        help="restrict to named monitoring group(s); repeatable (e.g. --group vn_domestic). Default: all groups.",
    )
    args = parser.parse_args(argv)

    from etl.ingestion.config import load_freshness_groups

    all_groups = load_freshness_groups()
    groups, unknown = select_groups(all_groups, args.group)
    if unknown:
        configured = ", ".join(g.name for g in all_groups) or "(none)"
        print(
            f"[freshness] unknown --group: {', '.join(unknown)}. Configured groups: {configured}",
            file=sys.stderr,
        )
        return 2
    if not groups:
        print("[freshness] no monitoring groups configured — nothing to check.", file=sys.stderr)
        return 2

    today = date.today()

    from app.db.session import get_session_factory

    session = get_session_factory()()
    should_fail = False
    warned = False
    try:
        for g in groups:
            latest = _latest_date(session, list(g.commodities))
            tag = "critical" if g.critical else "non-critical"
            verdict = classify(g, latest, today, args.strict)
            if verdict == "ok":
                print(f"[freshness] OK — {g.name} ({tag}): latest {latest} within {g.max_gap_days}d of {today}")
            else:
                print(
                    f"[freshness] STALE — {g.name} ({tag}): latest {latest} older than "
                    f"{g.max_gap_days}d before {today}",
                    file=sys.stderr,
                )
                if verdict == "fail":
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
