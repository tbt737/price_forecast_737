"""Read-only SUPPLY_DRIVER_AVAILABILITY_AUDIT for garlic / chili / onion.

Reports coverage of mechanistic supply drivers (``planted_area``,
``import_volume``, ``inventory`` + aliases) in ``fact_supply_demand_periodic``
and whether the production MV exposes matching columns. Never writes. Never
ingests. Never touches MV cutover.

Usage:
    python scripts/supply_driver_availability_audit.py
    python scripts/supply_driver_availability_audit.py --json

Exit codes:
    0 — audit completed (even if coverage is empty — that is a finding)
    2 — configuration / DB connection failure
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_DIR = _REPO_ROOT / "apps" / "api"
for _p in (_REPO_ROOT, _API_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ml.models.mechanistic_fourier import SUPPLY_ALIASES  # noqa: E402

# Produce profiles the business cares about (identifiers only — no name branches in engines).
DEFAULT_COMMODITY_CODES: tuple[str, ...] = (
    "DEHYDRATED_GARLIC",
    "CHINESE_GARLIC",
    "INDIAN_CHILIES",
    "DEHYDRATED_ONION",
    "RED_ONION_INDIA",
    "RED_ONION_CHINA",
)

# Liquid / public-data candidates for production-formula recheck (price-heavy).
LIQUID_COMMODITY_CODES: tuple[str, ...] = (
    "GOLD",
    "GOLD_VN",
    "ROBUSTA",
    "CRUDE_OIL",
    "CORN",
    "WHEAT",
    "SOYBEAN",
    "SUGAR",
    "COCOA",
    "COPPER",
    "PEPPER_VN",
    "RICE",
)

DRIVER_ROLES: tuple[str, ...] = ("planted_area", "import_volume", "inventory")

MIN_HISTORY = 252
DEFAULT_FOLDS = 5
DEFAULT_HORIZON = 30


@dataclass(frozen=True)
class MetricCoverage:
    role: str
    matched_metric_codes: list[str]
    n_rows: int
    n_non_null_value: int
    null_value_rate: float | None
    period_start_min: str | None
    period_end_max: str | None
    release_date_min: str | None
    release_date_max: str | None
    n_distinct_release_dates: int
    source_codes: list[str]
    approx_walk_forward_folds: int


@dataclass(frozen=True)
class CommodityAudit:
    commodity_code: str
    commodity_key: int | None
    price_n_positive: int
    price_date_min: str | None
    price_date_max: str | None
    price_approx_wf_folds_h30: int
    drivers: list[MetricCoverage]
    roles_with_data: list[str]
    roles_missing: list[str]
    mechanistic_ready: bool
    mv_columns_present: list[str]
    notes: list[str]


def metric_codes_for_role(role: str) -> tuple[str, ...]:
    return SUPPLY_ALIASES.get(role, (role,))


def approx_walk_forward_folds(
    n_obs: int,
    *,
    horizon: int = DEFAULT_HORIZON,
    min_train: int = MIN_HISTORY,
    folds: int = DEFAULT_FOLDS,
) -> int:
    """How many rolling-origin folds the current harness would attempt."""
    last_cut = n_obs - horizon
    if last_cut <= min_train:
        return 0
    cuts = np.unique(np.linspace(min_train, last_cut, folds).astype(int))
    return int(sum(1 for cut in cuts if cut >= min_train and cut + horizon <= n_obs))


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _alias_filter_sql(aliases: tuple[str, ...], *, prefix: str = "a") -> tuple[str, dict[str, str]]:
    """Build ``lower(metric_code) IN (...)`` params without expanding binds."""
    params = {f"{prefix}{i}": alias.lower() for i, alias in enumerate(aliases)}
    placeholders = ", ".join(f":{prefix}{i}" for i in range(len(aliases)))
    return f"lower(f.metric_code) IN ({placeholders})", params


def run_audit(
    session: Any,
    *,
    commodity_codes: tuple[str, ...] = DEFAULT_COMMODITY_CODES,
) -> list[CommodityAudit]:
    """Execute read-only coverage queries. ``session`` is a SQLAlchemy Session."""
    codes = tuple(c.upper() for c in commodity_codes)
    out: list[CommodityAudit] = []

    mv_cols_rows = session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'mv_ml_daily_features_wide'
            """
        )
    ).fetchall()
    mv_cols = {str(r[0]).lower() for r in mv_cols_rows}

    for code in codes:
        commodity = (
            session.execute(
                text("SELECT commodity_key, commodity_code FROM dim_commodity WHERE commodity_code = :code"),
                {"code": code},
            )
            .mappings()
            .first()
        )
        notes: list[str] = []
        if commodity is None:
            out.append(
                CommodityAudit(
                    commodity_code=code,
                    commodity_key=None,
                    price_n_positive=0,
                    price_date_min=None,
                    price_date_max=None,
                    price_approx_wf_folds_h30=0,
                    drivers=[],
                    roles_with_data=[],
                    roles_missing=list(DRIVER_ROLES),
                    mechanistic_ready=False,
                    mv_columns_present=[],
                    notes=["commodity not in dim_commodity"],
                )
            )
            continue

        key = int(commodity["commodity_key"])
        price = (
            session.execute(
                text(
                    """
                SELECT COUNT(*) FILTER (WHERE value > 0) AS n_pos,
                       MIN(price_date) FILTER (WHERE value > 0) AS dmin,
                       MAX(price_date) FILTER (WHERE value > 0) AS dmax
                FROM fact_price_daily
                WHERE commodity_key = :key
                """
                ),
                {"key": key},
            )
            .mappings()
            .one()
        )
        n_pos = int(price["n_pos"] or 0)
        price_folds = approx_walk_forward_folds(n_pos)

        drivers: list[MetricCoverage] = []
        roles_with: list[str] = []
        roles_missing: list[str] = []
        mv_present: list[str] = []

        for role in DRIVER_ROLES:
            aliases = metric_codes_for_role(role)
            for a in aliases:
                if a.lower() in mv_cols:
                    mv_present.append(a)

            filt, alias_params = _alias_filter_sql(aliases)
            rows = (
                session.execute(
                    text(
                        f"""
                    SELECT
                        f.metric_code,
                        COUNT(*) AS n_rows,
                        COUNT(f.value) AS n_non_null,
                        MIN(f.period_start) AS pmin,
                        MAX(f.period_end) AS pmax,
                        MIN(f.release_date) AS rmin,
                        MAX(f.release_date) AS rmax,
                        COUNT(DISTINCT f.release_date) AS n_rel,
                        ARRAY_REMOVE(ARRAY_AGG(DISTINCT ds.source_code), NULL) AS sources
                    FROM fact_supply_demand_periodic f
                    LEFT JOIN dim_data_source ds ON ds.data_source_key = f.data_source_key
                    WHERE f.commodity_key = :key
                      AND {filt}
                    GROUP BY f.metric_code
                    ORDER BY f.metric_code
                    """
                    ),
                    {"key": key, **alias_params},
                )
                .mappings()
                .all()
            )

            if not rows:
                roles_missing.append(role)
                drivers.append(
                    MetricCoverage(
                        role=role,
                        matched_metric_codes=[],
                        n_rows=0,
                        n_non_null_value=0,
                        null_value_rate=None,
                        period_start_min=None,
                        period_end_max=None,
                        release_date_min=None,
                        release_date_max=None,
                        n_distinct_release_dates=0,
                        source_codes=[],
                        approx_walk_forward_folds=0,
                    )
                )
                continue

            n_rows = sum(int(r["n_rows"] or 0) for r in rows)
            n_nn = sum(int(r["n_non_null"] or 0) for r in rows)
            null_rate = None if n_rows == 0 else float(1.0 - (n_nn / n_rows))
            sources: list[str] = []
            for r in rows:
                sources.extend([str(s) for s in (r["sources"] or [])])
            sources = sorted(set(sources))
            pmin = min((r["pmin"] for r in rows if r["pmin"] is not None), default=None)
            pmax = max((r["pmax"] for r in rows if r["pmax"] is not None), default=None)
            rmin = min((r["rmin"] for r in rows if r["rmin"] is not None), default=None)
            rmax = max((r["rmax"] for r in rows if r["rmax"] is not None), default=None)
            n_rel = sum(int(r["n_rel"] or 0) for r in rows)
            role_folds = approx_walk_forward_folds(n_rel, horizon=1, min_train=12, folds=5)

            roles_with.append(role)
            drivers.append(
                MetricCoverage(
                    role=role,
                    matched_metric_codes=[str(r["metric_code"]) for r in rows],
                    n_rows=n_rows,
                    n_non_null_value=n_nn,
                    null_value_rate=null_rate,
                    period_start_min=_iso(pmin),
                    period_end_max=_iso(pmax),
                    release_date_min=_iso(rmin),
                    release_date_max=_iso(rmax),
                    n_distinct_release_dates=n_rel,
                    source_codes=sources,
                    approx_walk_forward_folds=role_folds,
                )
            )

        ready = len(roles_missing) == 0 and price_folds > 0
        if price_folds == 0:
            notes.append(f"price history too short for walk-forward (n_pos={n_pos}, need >{MIN_HISTORY}+30)")
        if roles_missing:
            notes.append(f"missing supply roles: {', '.join(roles_missing)}")
        if not mv_present:
            notes.append("no matching driver columns on mv_ml_daily_features_wide")

        out.append(
            CommodityAudit(
                commodity_code=code,
                commodity_key=key,
                price_n_positive=n_pos,
                price_date_min=_iso(price["dmin"]),
                price_date_max=_iso(price["dmax"]),
                price_approx_wf_folds_h30=price_folds,
                drivers=drivers,
                roles_with_data=roles_with,
                roles_missing=roles_missing,
                mechanistic_ready=ready,
                mv_columns_present=sorted(set(mv_present)),
                notes=notes,
            )
        )
    return out


AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
EXIT_UNAVAILABLE = 2
EXIT_OK = 0


def classify_database_host(url: str) -> str:
    """Return host kind without logging credentials.

    ``supabase_direct`` is the IPv6-only ``db.<ref>.supabase.co`` host that often
    fails on IPv4-only networks; prefer Session pooler (``*.pooler.supabase.com``).
    """
    host = (make_url(url).host or "").lower()
    if "pooler.supabase.com" in host:
        return "supabase_session_pooler"
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return "supabase_direct"
    return "other"


def emit_audit_unavailable(reason: str, *, host_kind: str | None = None) -> int:
    """Fail closed: connection/DNS errors are not empty-coverage findings."""
    print(f"verdict: {AUDIT_UNAVAILABLE}", flush=True)
    print(f"reason: {reason}", file=sys.stderr)
    if host_kind == "supabase_direct":
        print(
            "hint: DATABASE_URL uses db.*.supabase.co (often IPv6-only). "
            "Use Supabase Session Pooler IPv4 (*.pooler.supabase.com:5432) — see DEPLOY.md §0.",
            file=sys.stderr,
        )
    elif host_kind is not None:
        print(f"host_kind: {host_kind}", file=sys.stderr)
    # Never emit a CommodityAudit payload here — that would look like mechanistic_ready=false.
    return EXIT_UNAVAILABLE


def list_all_commodity_codes(session: Any) -> tuple[str, ...]:
    """All commodity codes in dim_commodity (sorted)."""
    rows = session.execute(text("SELECT commodity_code FROM dim_commodity ORDER BY commodity_code")).fetchall()
    return tuple(str(r[0]).upper() for r in rows)


def format_ready_summary(audits: list[CommodityAudit]) -> str:
    """Compact table: which codes are formula-recheck candidates."""
    lines = [
        "",
        "READY SUMMARY",
        "-" * 60,
        f"{'code':<22} {'price_n':>8} {'wf30':>5} {'roles':>8} {'mech':>5} {'mv_cols':>7}",
    ]
    for a in sorted(audits, key=lambda x: (-int(x.mechanistic_ready), -x.price_n_positive, x.commodity_code)):
        lines.append(
            f"{a.commodity_code:<22} {a.price_n_positive:>8} {a.price_approx_wf_folds_h30:>5} "
            f"{len(a.roles_with_data):>8} {str(a.mechanistic_ready):>5} {len(a.mv_columns_present):>7}"
        )
    price_ok = [a for a in audits if a.price_approx_wf_folds_h30 > 0]
    mech_ok = [a for a in audits if a.mechanistic_ready]
    lines.append("-" * 60)
    lines.append(f"price_walkforward_ok={len(price_ok)}/{len(audits)}  mechanistic_ready={len(mech_ok)}/{len(audits)}")
    if mech_ok:
        lines.append("mechanistic_ready codes: " + ", ".join(a.commodity_code for a in mech_ok))
    if price_ok:
        lines.append("price_ok codes (production formula recheck): " + ", ".join(a.commodity_code for a in price_ok))
    return "\n".join(lines)


def format_report(audits: list[CommodityAudit]) -> str:
    lines: list[str] = [
        "SUPPLY_DRIVER_AVAILABILITY_AUDIT (read-only)",
        "=" * 60,
    ]
    for a in audits:
        lines.append(f"\n## {a.commodity_code}  (key={a.commodity_key})")
        lines.append(
            f"  price: n_pos={a.price_n_positive}  "
            f"[{a.price_date_min} .. {a.price_date_max}]  "
            f"wf_folds_h30≈{a.price_approx_wf_folds_h30}"
        )
        lines.append(f"  mechanistic_ready: {a.mechanistic_ready}")
        lines.append(f"  roles_with_data: {a.roles_with_data or '—'}")
        lines.append(f"  roles_missing: {a.roles_missing or '—'}")
        lines.append(f"  mv_columns_present: {a.mv_columns_present or '—'}")
        for d in a.drivers:
            lines.append(
                f"  - {d.role}: metrics={d.matched_metric_codes or '[]'}  "
                f"rows={d.n_rows}  null_rate={d.null_value_rate}  "
                f"period=[{d.period_start_min}..{d.period_end_max}]  "
                f"release=[{d.release_date_min}..{d.release_date_max}]  "
                f"n_release={d.n_distinct_release_dates}  "
                f"sources={d.source_codes or '[]'}  "
                f"wf_folds≈{d.approx_walk_forward_folds}"
            )
        for note in a.notes:
            lines.append(f"  NOTE: {note}")
    ready_n = sum(1 for a in audits if a.mechanistic_ready)
    price_n = sum(1 for a in audits if a.price_approx_wf_folds_h30 > 0)
    lines.append("\n" + "=" * 60)
    lines.append(f"summary: {ready_n}/{len(audits)} commodities mechanistic_ready")
    lines.append(f"summary: {price_n}/{len(audits)} commodities price_walkforward_ok (n folds>0)")
    lines.append(format_ready_summary(audits))
    lines.append("gate: do NOT add drivers to canonical MV / ingest / cutover until coverage is sufficient.")
    lines.append("next: for price_walkforward_ok codes, run scripts/recheck_price_formula.py (read-only).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument(
        "--commodity",
        action="append",
        dest="commodities",
        help="Commodity code (repeatable). Default: garlic/chili/onion set.",
    )
    parser.add_argument(
        "--liquid",
        action="store_true",
        help="Audit LIQUID_COMMODITY_CODES (gold/robusta/grains/…) for formula recheck.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Audit every commodity in dim_commodity (read-only discovery).",
    )
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env")
    except ImportError:
        pass

    host_kind: str | None = None
    try:
        from app.core.config import get_settings
        from app.db.session import get_session_factory

        db_url = get_settings().resolved_database_url()
        host_kind = classify_database_host(db_url)
    except Exception as exc:  # noqa: BLE001
        return emit_audit_unavailable(f"cannot resolve DATABASE_URL / session factory: {exc}")

    if host_kind == "supabase_direct":
        print(
            "warning: DATABASE_URL looks like Supabase direct (db.*.supabase.co). "
            "Prefer Session Pooler IPv4 if connect fails — DEPLOY.md §0.",
            file=sys.stderr,
        )

    try:
        session = get_session_factory()()
    except Exception as exc:  # noqa: BLE001
        return emit_audit_unavailable(f"session open failed: {exc}", host_kind=host_kind)

    try:
        try:
            session.execute(text("SET TRANSACTION READ ONLY"))
        except Exception:  # noqa: BLE001
            pass
        session.execute(text("SELECT 1"))
        if args.all:
            codes = list_all_commodity_codes(session)
        elif args.liquid:
            codes = LIQUID_COMMODITY_CODES
        elif args.commodities:
            codes = tuple(args.commodities)
        else:
            codes = DEFAULT_COMMODITY_CODES
        audits = run_audit(session, commodity_codes=codes)
    except Exception as exc:  # noqa: BLE001
        return emit_audit_unavailable(f"database unreachable or query failed: {exc}", host_kind=host_kind)
    finally:
        session.close()

    if args.json:
        payload = {
            "verdict": "AUDIT_OK",
            "host_kind": host_kind,
            "commodities": [asdict(a) for a in audits],
        }
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"verdict: AUDIT_OK  (host_kind={host_kind})")
        print(format_report(audits))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
