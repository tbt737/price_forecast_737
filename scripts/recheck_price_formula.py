"""Read-only recheck of the production price-forecast formula on liquid series.

Loads ``CommodityPricePredictor`` / ``forecast_commodity`` for commodities that
already have enough positive price history (walk-forward folds > 0). Reports
model selection + MAPE — never writes, never ingests, never touches MV cutover.

Mechanistic cash-flow is only reported when supply drivers are present (same
gate as SUPPLY_DRIVER_AVAILABILITY_AUDIT).

Usage:
    $env:DATABASE_URL = "<SESSION_POOLER_URI>"   # pooler host required
    $env:PYTHONPATH = ".;apps/api"
    python scripts/recheck_price_formula.py --liquid
    python scripts/recheck_price_formula.py --commodity GOLD --commodity ROBUSTA
    Remove-Item Env:DATABASE_URL
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_DIR = _REPO_ROOT / "apps" / "api"
for _p in (_REPO_ROOT, _API_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ml.forecast import MIN_HISTORY, forecast_commodity  # noqa: E402
from scripts.supply_driver_availability_audit import (  # noqa: E402
    AUDIT_UNAVAILABLE,
    EXIT_OK,
    EXIT_UNAVAILABLE,
    LIQUID_COMMODITY_CODES,
    classify_database_host,
    emit_audit_unavailable,
    run_audit,
)


def _horizon_summary(result: dict[str, Any], horizon: int = 30) -> dict[str, Any]:
    if not result.get("available"):
        return {
            "available": False,
            "reason": result.get("reason"),
            "commodity_code": result.get("commodity_code"),
        }
    hz = (result.get("horizons") or {}).get(str(horizon)) or {}
    bt = hz.get("backtest") or {}
    return {
        "available": True,
        "commodity_code": result.get("commodity_code"),
        "instrument_code": result.get("instrument_code"),
        "history_points": result.get("history_points"),
        "last_date": result.get("last_date"),
        "last_price": result.get("last_price"),
        "horizon": horizon,
        "model_used": hz.get("model_used"),
        "mape_pct": bt.get("mape_pct"),
        "naive_mape_pct": bt.get("naive_mape_pct"),
        "beats_naive": bt.get("beats_naive"),
        "candidates": bt.get("candidates"),
        "ou_considered": bt.get("ou_considered"),
        "mechanistic_considered": bt.get("mechanistic_considered"),
    }


def format_recheck(rows: list[dict[str, Any]]) -> str:
    lines = [
        "PRICE_FORMULA_RECHECK (read-only)",
        "=" * 60,
    ]
    for r in rows:
        code = r.get("commodity_code", "?")
        if not r.get("available"):
            lines.append(f"\n## {code}\n  unavailable: {r.get('reason')}")
            continue
        lines.append(f"\n## {code}")
        lines.append(
            f"  history={r.get('history_points')}  last={r.get('last_date')}  "
            f"price={r.get('last_price')}  instrument={r.get('instrument_code')}"
        )
        lines.append(
            f"  model_used={r.get('model_used')}  mape={r.get('mape_pct')}  "
            f"naive={r.get('naive_mape_pct')}  beats_naive={r.get('beats_naive')}"
        )
        lines.append(f"  candidates={r.get('candidates')}")
        lines.append(
            f"  ou_considered={r.get('ou_considered')}  mechanistic_considered={r.get('mechanistic_considered')}"
        )
    ok = sum(1 for r in rows if r.get("available"))
    beat = sum(1 for r in rows if r.get("beats_naive"))
    lines.append("\n" + "=" * 60)
    lines.append(f"summary: available={ok}/{len(rows)}  beats_naive={beat}/{ok if ok else 0}")
    lines.append("gate: no MV/ingest/cutover from this script.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--commodity", action="append", dest="commodities")
    parser.add_argument(
        "--liquid",
        action="store_true",
        help="Recheck LIQUID_COMMODITY_CODES (default if no --commodity).",
    )
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument(
        "--enable-ou",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env")
    except ImportError:
        pass

    try:
        from app.core.config import get_settings
        from app.db.session import get_session_factory

        host_kind = classify_database_host(get_settings().resolved_database_url())
    except Exception as exc:  # noqa: BLE001
        return emit_audit_unavailable(f"cannot resolve DATABASE_URL: {exc}")

    if host_kind == "supabase_direct":
        print(
            "warning: prefer Session Pooler IPv4 (*.pooler.supabase.com) — DEPLOY.md §0.",
            file=sys.stderr,
        )

    codes: tuple[str, ...]
    if args.commodities:
        codes = tuple(c.upper() for c in args.commodities)
    else:
        codes = LIQUID_COMMODITY_CODES

    session = get_session_factory()()
    rows: list[dict[str, Any]] = []
    try:
        try:
            session.execute(text("SET TRANSACTION READ ONLY"))
        except Exception:  # noqa: BLE001
            pass
        session.execute(text("SELECT 1"))

        # Pre-filter: only codes with enough price history (or report unavailable).
        audits = {a.commodity_code: a for a in run_audit(session, commodity_codes=codes)}
        for code in codes:
            audit = audits.get(code)
            if audit is None or audit.commodity_key is None:
                rows.append({"available": False, "commodity_code": code, "reason": "unknown commodity"})
                continue
            if audit.price_n_positive < MIN_HISTORY:
                rows.append(
                    {
                        "available": False,
                        "commodity_code": code,
                        "reason": (f"need >= {MIN_HISTORY} positive prices, have {audit.price_n_positive}"),
                        "mechanistic_ready": audit.mechanistic_ready,
                        "roles_with_data": audit.roles_with_data,
                    }
                )
                continue
            try:
                result = forecast_commodity(session, code, horizons=(args.horizon,), enable_ou=bool(args.enable_ou))
                summary = _horizon_summary(result, horizon=args.horizon)
                summary["mechanistic_ready_audit"] = audit.mechanistic_ready
                summary["roles_with_data"] = audit.roles_with_data
                rows.append(summary)
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "available": False,
                        "commodity_code": code,
                        "reason": f"forecast error: {type(exc).__name__}: {exc}",
                    }
                )
    except Exception as exc:  # noqa: BLE001
        print(f"verdict: {AUDIT_UNAVAILABLE}", flush=True)
        print(f"reason: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    finally:
        session.close()

    if args.json:
        print(
            json.dumps(
                {"verdict": "RECHECK_OK", "host_kind": host_kind, "results": rows},
                indent=2,
                default=str,
            )
        )
    else:
        print(f"verdict: RECHECK_OK  (host_kind={host_kind})")
        print(format_recheck(rows))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
