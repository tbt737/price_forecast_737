"""Forecast accuracy evaluator (Phase ACC-1D-A).

Fills in `actual_price` / errors and flips `status` for matured `pending` rows in
`fact_forecast_log` once the real price is available. **Defaults to DRY-RUN**: it
reads + decides + prints a summary, but updates nothing; `--write` is required to
update. Never fabricates an actual — a row with no actual stays `pending` until it
ages past `--expire-after-days`, then becomes `expired` (only on `--write`).

The first controlled production `--write` is a separate audited phase. Never prints
DATABASE_URL. Pure helpers (`compute_errors`, `decide`, `nearest_actual`) are unit-tested.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "apps" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ALLOWED_HORIZONS = (30, 90)
_CODE_RE = re.compile(r"[A-Z0-9_]{1,64}")
DEFAULT_GRACE_DAYS = 4       # window to accept the nearest NEXT trading-day actual
DEFAULT_EXPIRE_DAYS = 7      # mark expired once target is older than this and no actual

SELECT_PENDING_SQL = """
SELECT forecast_log_id, commodity_code, as_of_date, target_date, horizon_days, model_used, predicted_price
FROM fact_forecast_log
WHERE status = 'pending' AND target_date <= :as_of
{filters}
ORDER BY target_date, forecast_log_id
{limit}
"""

# Same primary-instrument choice as ml.forecast.load_price_series (most rows), so the
# actual is read on the exact series the forecast was made from.
LOOKUP_ACTUAL_SQL = """
WITH ck AS (SELECT commodity_key FROM dim_commodity WHERE commodity_code = :code),
     ik AS (
        SELECT f.market_instrument_key
        FROM fact_price_daily f, ck
        WHERE f.commodity_key = ck.commodity_key
        GROUP BY f.market_instrument_key ORDER BY count(*) DESC LIMIT 1)
SELECT f.price_date, f.value
FROM fact_price_daily f, ck, ik
WHERE f.commodity_key = ck.commodity_key AND f.market_instrument_key = ik.market_instrument_key
  AND f.value IS NOT NULL AND f.value > 0
  AND f.price_date >= :target AND f.price_date <= :hi
ORDER BY f.price_date ASC
"""

UPDATE_EVALUATED_SQL = """
UPDATE fact_forecast_log
SET actual_price = :actual_price, actual_available_at = now(),
    absolute_error = :absolute_error, absolute_percentage_error = :absolute_percentage_error,
    status = 'evaluated', evaluated_at = now()
WHERE forecast_log_id = :id AND status = 'pending'
"""

UPDATE_EXPIRED_SQL = """
UPDATE fact_forecast_log
SET status = 'expired', evaluated_at = now()
WHERE forecast_log_id = :id AND status = 'pending'
"""


def compute_errors(predicted: float, actual: float) -> tuple[float, float] | None:
    """(absolute_error, absolute_percentage_error). None if actual is not > 0."""
    if actual is None or actual <= 0:
        return None
    ae = abs(actual - predicted)
    return ae, ae / actual * 100.0


def nearest_actual(rows: Iterable[tuple[date, float]], target: date, grace_days: int) -> tuple[date, float] | None:
    """Earliest priced day in [target, target+grace] with value>0 — never a date before
    target, never beyond the grace window. Used to tolerate a weekend/holiday target."""
    best: tuple[date, float] | None = None
    for d, v in rows:
        if v is None or v <= 0 or d < target or (d - target).days > grace_days:
            continue
        if best is None or d < best[0]:
            best = (d, v)
    return best


def decide(
    predicted: float, target_date: date, actual: float | None, as_of: date, expire_after_days: int
) -> dict[str, Any]:
    """Decide the action for one pending row. Never fabricates an actual."""
    if actual is not None and actual > 0:
        ae, ape = compute_errors(predicted, actual)  # type: ignore[misc]
        return {
            "status": "evaluated",
            "actual_price": actual,
            "absolute_error": ae,
            "absolute_percentage_error": ape,
        }
    if (as_of - target_date).days > expire_after_days:
        return {"status": "expired"}
    return {"status": "pending"}


def _select_pending(
    session: Any,
    as_of: date,
    commodities: list[str] | None,
    horizons: list[int] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    filters, params = "", {"as_of": as_of}
    if commodities:
        filters += " AND commodity_code = ANY(:codes)"
        params["codes"] = commodities
    if horizons:
        filters += " AND horizon_days = ANY(:horizons)"
        params["horizons"] = horizons
    sql = SELECT_PENDING_SQL.format(filters=filters, limit="LIMIT :limit" if limit else "")
    if limit:
        params["limit"] = limit
    return [dict(r._mapping) for r in session.execute(text(sql), params).all()]


def _lookup_actual(session: Any, commodity_code: str, target: date, grace_days: int) -> float | None:
    from sqlalchemy import text

    rows = session.execute(
        text(LOOKUP_ACTUAL_SQL), {"code": commodity_code, "target": target, "hi": target + timedelta(days=grace_days)}
    ).all()
    hit = nearest_actual([(r[0], float(r[1])) for r in rows], target, grace_days)
    return hit[1] if hit else None


def _open_session() -> Any:
    from app.db.session import get_session_factory

    return get_session_factory()()


def evaluate(
    session: Any,
    *,
    as_of: date,
    commodities: list[str] | None,
    horizons: list[int] | None,
    limit: int | None,
    grace_days: int,
    expire_after_days: int,
    lookup_fn: Callable[..., float | None] | None = None,
) -> list[dict[str, Any]]:
    """Return one action per due pending row: {row, decision}. No DB writes here."""
    look = lookup_fn or _lookup_actual
    actions: list[dict[str, Any]] = []
    for row in _select_pending(session, as_of, commodities, horizons, limit):
        actual = look(session, row["commodity_code"], row["target_date"], grace_days)
        decision = decide(float(row["predicted_price"]), row["target_date"], actual, as_of, expire_after_days)
        actions.append({"row": row, "decision": decision})
    return actions


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Forecast accuracy evaluator (dry-run by default).")
    p.add_argument("--write", action="store_true", help="apply updates (default: dry-run, no writes)")
    p.add_argument("--as-of", dest="as_of", default=None, help="YYYY-MM-DD; default today")
    p.add_argument("--commodities", nargs="*", default=None)
    p.add_argument("--horizons", nargs="*", type=int, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--grace-days", type=int, default=DEFAULT_GRACE_DAYS, help="accept nearest next actual within N days"
    )
    p.add_argument("--expire-after-days", dest="expire_after_days", type=int, default=DEFAULT_EXPIRE_DAYS)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.horizons:
        bad = [h for h in args.horizons if h not in ALLOWED_HORIZONS]
        if bad:
            print(f"Error: invalid horizons {bad}", file=sys.stderr)
            return 2
    codes = None
    if args.commodities:
        codes = [c.upper() for c in args.commodities]
        bad_c = [c for c in codes if not _CODE_RE.fullmatch(c)]
        if bad_c:
            print(f"Error: invalid commodity codes {bad_c}", file=sys.stderr)
            return 2
    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    except ValueError:
        print("Error: --as-of must be YYYY-MM-DD", file=sys.stderr)
        return 2

    session = _open_session()
    try:
        actions = evaluate(
            session, as_of=as_of, commodities=codes, horizons=args.horizons, limit=args.limit,
            grace_days=args.grace_days, expire_after_days=args.expire_after_days,
        )
        ev = [a for a in actions if a["decision"]["status"] == "evaluated"]
        ex = [a for a in actions if a["decision"]["status"] == "expired"]
        keep = [a for a in actions if a["decision"]["status"] == "pending"]

        if not args.write:
            print(
                f"[dry-run] as_of={as_of}: {len(actions)} due — would evaluate {len(ev)}, "
                f"expire {len(ex)}, keep pending {len(keep)}."
            )
            for a in (ev + ex)[:30]:
                r, d = a["row"], a["decision"]
                extra = (
                    f"actual={d.get('actual_price')} ape={d.get('absolute_percentage_error'):.2f}%"
                    if d["status"] == "evaluated"
                    else ""
                )
                print(
                    f"  {d['status']:9} {r['commodity_code']:16} "
                    f"target={r['target_date']} h={r['horizon_days']} {extra}"
                )
            print("[dry-run] no rows updated — pass --write to apply.")
            return 0

        from sqlalchemy import text

        session.rollback()  # end the read transaction before writing
        ev_n = ex_n = 0
        for a in ev:
            r, d = a["row"], a["decision"]
            ev_n += session.execute(text(UPDATE_EVALUATED_SQL), {
                "id": r["forecast_log_id"], "actual_price": d["actual_price"],
                "absolute_error": d["absolute_error"], "absolute_percentage_error": d["absolute_percentage_error"],
            }).rowcount or 0
        for a in ex:
            ex_n += session.execute(text(UPDATE_EXPIRED_SQL), {"id": a["row"]["forecast_log_id"]}).rowcount or 0
        session.commit()
        print(f"[write] as_of={as_of}: evaluated={ev_n}, expired={ex_n}, kept pending={len(keep)}.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
