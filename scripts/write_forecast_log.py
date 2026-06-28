"""Shadow forecast-log writer (Phase ACC-1C-A).

Generates `pending` rows for `fact_forecast_log` from the existing production
forecaster (`ml.forecast.forecast_commodity` — NOT modified). **Defaults to DRY-RUN**:
it reads prices + computes forecasts and prints a summary, but inserts nothing.
`--write` is required to insert, and inserts are idempotent via
`ON CONFLICT (...) DO NOTHING` on the unique grain. Rows stay `pending` until a
later evaluator fills actuals — no accuracy is known yet. Never prints DATABASE_URL.

This phase (ACC-1C-A) ships the code + offline tests only; the first controlled
production `--write` is a separate audited phase (ACC-1C-B).

Usage:
    python scripts/write_forecast_log.py                       # dry-run, all approved commodities
    python scripts/write_forecast_log.py --commodities ROBUSTA --horizons 30 --limit 1
    python scripts/write_forecast_log.py --write              # insert (ACC-1C-B only, after audit)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

# The forecaster lives in the repo-root ``ml`` package; the session factory in the
# FastAPI app package. Add BOTH to sys.path so this runs as a standalone script
# (python scripts/write_forecast_log.py), where sys.path[0] is scripts/, not the root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "apps" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

WRITER_VERSION = "acc-1c-a"
ALLOWED_HORIZONS = (30, 90)
APPROVED_COMMODITIES = (
    "GOLD", "CRUDE_OIL", "CORN", "WHEAT", "COPPER", "SUGAR", "SOYBEAN", "COCOA", "RICE",
    "ROBUSTA", "RED_ONION_INDIA", "INDIAN_CHILIES", "CHINESE_GARLIC", "PEANUTS",
)
_CODE_RE = re.compile(r"[A-Z0-9_]{1,64}")

# Idempotent insert on the table's unique grain — never updates existing rows.
INSERT_SQL = """
INSERT INTO fact_forecast_log
    (forecast_run_id, commodity_code, as_of_date, target_date, horizon_days, model_used,
     predicted_price, baseline_price, status, metadata_json)
VALUES
    (:forecast_run_id, :commodity_code, :as_of_date, :target_date, :horizon_days, :model_used,
     :predicted_price, :baseline_price, :status, CAST(:metadata_json AS JSONB))
ON CONFLICT (commodity_code, as_of_date, target_date, horizon_days, model_used) DO NOTHING
"""


def business_days_ahead(start: date, n: int) -> date:
    """The n-th business day after ``start`` (skips Sat/Sun). Holiday calendars are
    NOT applied — see the docs for that approximation limitation."""
    if n <= 0:
        raise ValueError("n must be positive")
    cur, added = start, 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def new_run_id() -> str:
    """Stable id generated once per run (UTC timestamp + short uuid)."""
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def forecast_to_rows(result: dict[str, Any], *, run_id: str, run_mode: str, version: str = WRITER_VERSION) -> list[dict[str, Any]]:
    """Map one ``forecast_commodity`` result to pending forecast-log rows (one per
    horizon). Unavailable / malformed / non-positive forecasts yield no rows."""
    if not result or not result.get("available"):
        return []
    code, last_date, last_price = result.get("commodity_code"), result.get("last_date"), result.get("last_price")
    if not (code and last_date and last_price):
        return []
    as_of = date.fromisoformat(last_date)
    baseline = float(last_price)
    rows: list[dict[str, Any]] = []
    for h_str, hz in (result.get("horizons") or {}).items():
        try:
            horizon = int(h_str)
        except (TypeError, ValueError):
            continue
        if horizon not in ALLOWED_HORIZONS:
            continue
        points = hz.get("points") or []
        if not points:
            continue
        try:
            predicted = float(points[-1]["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if predicted <= 0:  # honour the table CHECK (predicted_price > 0)
            continue
        bt = hz.get("backtest") or {}
        rows.append(
            {
                "forecast_run_id": run_id,
                "commodity_code": code,
                "as_of_date": as_of,
                "target_date": business_days_ahead(as_of, horizon),
                "horizon_days": horizon,
                "model_used": hz.get("model_used") or "naive",
                "predicted_price": predicted,
                "baseline_price": baseline,
                "status": "pending",
                "metadata_json": {
                    "candidates": bt.get("candidates"),
                    "ou_considered": bt.get("ou_considered"),
                    "mape_pct": bt.get("mape_pct"),
                    "naive_mape_pct": bt.get("naive_mape_pct"),
                    "beats_naive": bt.get("beats_naive"),
                    "source": "forecast_commodity",
                    "run_mode": run_mode,
                    "version": version,
                },
            }
        )
    return rows


def _default_forecast_fn(session: Any, code: str, *, horizons: tuple[int, ...]) -> dict[str, Any]:
    from ml.forecast import forecast_commodity  # imported lazily — no side effects at module import

    return forecast_commodity(session, code, horizons=horizons)


def generate_rows(
    session: Any,
    codes: list[str],
    horizons: list[int],
    *,
    run_id: str,
    run_mode: str,
    as_of: date | None = None,
    forecast_fn: Callable[..., dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Run the forecaster per commodity and map to rows. A single failing/unavailable
    commodity is SKIPPED (recorded), never crashing the whole run."""
    fn = forecast_fn or _default_forecast_fn
    rows: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    for code in codes:
        try:
            result = fn(session, code, horizons=tuple(horizons))
        except Exception as exc:  # noqa: BLE001 — one bad commodity must not abort the batch
            skipped.append((code, f"error: {type(exc).__name__}"))
            continue
        if not result or not result.get("available"):
            skipped.append((code, (result or {}).get("reason", "unavailable")))
            continue
        if as_of is not None and result.get("last_date") != as_of.isoformat():
            skipped.append((code, f"last_date {result.get('last_date')} != --as-of {as_of}"))
            continue
        produced = forecast_to_rows(result, run_id=run_id, run_mode=run_mode)
        if produced:
            rows.extend(produced)
        else:
            skipped.append((code, "no usable horizon"))
    return rows, skipped


def _open_session() -> Any:
    from app.db.session import get_session_factory

    return get_session_factory()()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Shadow forecast-log writer (dry-run by default).")
    p.add_argument("--write", action="store_true", help="insert rows (default: dry-run, no writes)")
    p.add_argument("--commodities", nargs="*", default=None, help="allowlist of commodity codes")
    p.add_argument("--horizons", nargs="*", type=int, default=list(ALLOWED_HORIZONS), help="30 and/or 90")
    p.add_argument("--as-of", dest="as_of", default=None, help="YYYY-MM-DD; only log forecasts anchored here")
    p.add_argument("--limit", type=int, default=None, help="cap number of commodities (smoke)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    bad_h = [h for h in args.horizons if h not in ALLOWED_HORIZONS]
    if bad_h:
        print(f"Error: invalid horizons {bad_h} (allowed: {list(ALLOWED_HORIZONS)})", file=sys.stderr)
        return 2
    codes = [c.upper() for c in (args.commodities or APPROVED_COMMODITIES)]
    bad_c = [c for c in codes if not _CODE_RE.fullmatch(c)]
    if bad_c:
        print(f"Error: invalid commodity codes {bad_c}", file=sys.stderr)
        return 2
    if args.limit is not None:
        codes = codes[: max(0, args.limit)]
    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else None
    except ValueError:
        print("Error: --as-of must be YYYY-MM-DD", file=sys.stderr)
        return 2

    run_id = new_run_id()
    run_mode = "write" if args.write else "dry_run"
    session = _open_session()
    try:
        rows, skipped = generate_rows(session, codes, args.horizons, run_id=run_id, run_mode=run_mode, as_of=as_of)

        if not args.write:
            print(f"[dry-run] run_id={run_id}: would write {len(rows)} row(s), {len(skipped)} skipped.")
            for r in rows[:20]:
                print(
                    f"  {r['commodity_code']:16} as_of={r['as_of_date']} h={r['horizon_days']:>2} "
                    f"target={r['target_date']} model={r['model_used']:8} pred={r['predicted_price']}"
                )
            for code, why in skipped:
                print(f"  SKIP {code}: {why}")
            print("[dry-run] no rows inserted — pass --write to insert.")
            return 0

        from sqlalchemy import text

        # End the implicit read-only transaction opened while forecasting, then insert
        # in a fresh transaction (forecast_commodity issues SELECTs, so the Session is
        # already mid-transaction — an explicit begin() here would raise).
        session.rollback()
        inserted = 0
        for r in rows:
            params = {**r, "metadata_json": json.dumps(r["metadata_json"])}
            inserted += session.execute(text(INSERT_SQL), params).rowcount or 0
        session.commit()
        print(
            f"[write] run_id={run_id}: inserted={inserted}/{len(rows)} "
            f"({len(rows) - inserted} already present, {len(skipped)} commodity-skipped)."
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
