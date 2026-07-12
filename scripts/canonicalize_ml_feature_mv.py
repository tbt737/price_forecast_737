"""Single-connection canonicalize runner for ``mv_ml_daily_features_wide``.

Holds a **session-level** ``pg_advisory_lock`` across the full chain
(rename → create MV → unique index → initial non-CONCURRENTLY refresh →
REVOKE on MV + backup), inside **one transaction** so failure auto-rolls back.
Dry-run by default (INV-7). ``--write`` is the ONLY supported production apply
path (do not run loose multi-file psql).

Exit codes:
  0 — dry-run ok / write + parity smoke passed
  1 — refused or write failed (transaction rolled back; lock released)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_API = _ROOT / "apps" / "api"
sys.path[:0] = [str(_API), str(_ROOT)]

from sqlalchemy import text  # noqa: E402

MV = "mv_ml_daily_features_wide"
BAK = "mv_ml_daily_features_wide_table_bak"
BAK_IDX = "uq_mv_ml_daily_features_wide_table_bak"
UQ = "uq_mv_ml_daily_features_wide"
LOCK_KEY = "ml_feature_view_canonicalize"

GEN_010 = _ROOT / "db" / "views" / "generated" / "010_mv_ml_daily_features_wide.sql"
IDX_011 = _ROOT / "db" / "views" / "011_indexes_ml_feature_views.sql"


def _mv_sql_create_only() -> str:
    raw = GEN_010.read_text(encoding="utf-8")
    body = re.sub(
        r"CREATE MATERIALIZED VIEW IF NOT EXISTS",
        "CREATE MATERIALIZED VIEW",
        raw,
        count=1,
    )
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    create = next(s for s in stmts if "CREATE MATERIALIZED VIEW" in s)
    return create


def _index_sql() -> str:
    raw = IDX_011.read_text(encoding="utf-8")
    stmts = [s.strip() for s in raw.split(";") if s.strip() and "CREATE UNIQUE INDEX" in s]
    if not stmts:
        raise RuntimeError("011 unique index statement not found")
    return stmts[0]


def _relkind(conn: Any, name: str) -> str | None:
    return conn.execute(
        text(
            """
            SELECT c.relkind::text
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = :n
            """
        ),
        {"n": name},
    ).scalar()


def _index_exists(conn: Any, name: str) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT EXISTS (
                  SELECT 1 FROM pg_class i
                  JOIN pg_namespace n ON n.oid = i.relnamespace
                  WHERE n.nspname = 'public' AND i.relname = :n AND i.relkind = 'i'
                )
                """
            ),
            {"n": name},
        ).scalar()
    )


def _revoke_public_roles(conn: Any, name: str) -> None:
    for role in ("PUBLIC", "anon", "authenticated"):
        conn.execute(text(f'REVOKE ALL ON TABLE public."{name}" FROM {role}'))


def _parity_smoke(conn: Any) -> dict[str, Any]:
    kind = _relkind(conn, MV)
    rows = int(conn.execute(text(f'SELECT COUNT(*) FROM public."{MV}"')).scalar_one())
    grain = int(
        conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM (
                  SELECT commodity_key, as_of_date
                  FROM public."{MV}"
                  GROUP BY commodity_key, as_of_date
                  HAVING COUNT(*) > 1
                ) d
                """
            )
        ).scalar_one()
    )
    dmax = conn.execute(text(f'SELECT MAX(as_of_date) FROM public."{MV}"')).scalar()
    n_comm = int(
        conn.execute(text(f'SELECT COUNT(DISTINCT commodity_key) FROM public."{MV}"')).scalar_one()
    )
    has_uq = _index_exists(conn, UQ)
    ok = kind == "m" and grain == 0 and has_uq and rows > 0
    return {
        "ok": ok,
        "relkind": kind,
        "rows": rows,
        "duplicate_grains": grain,
        "max_as_of_date": None if dmax is None else str(dmax),
        "distinct_commodity_keys": n_comm,
        "unique_index": has_uq,
    }


def plan_dry_run(conn: Any) -> dict[str, Any]:
    return {
        "lock": f"pg_advisory_lock(hashtext('{LOCK_KEY}')) — session scope, whole chain",
        "transaction": "single connection transaction — failure auto-rollback",
        "mv_relkind": _relkind(conn, MV),
        "backup_exists": _relkind(conn, BAK) is not None,
        "backup_relkind": _relkind(conn, BAK),
        "create_sql_head": _mv_sql_create_only().splitlines()[0],
        "index_sql": _index_sql(),
        "steps": [
            "session advisory lock",
            "BEGIN",
            "fail-closed if backup name exists",
            "rename TABLE→backup + rename unique index (if relkind=r)",
            "REVOKE on backup",
            "CREATE MATERIALIZED VIEW … WITH NO DATA (no IF NOT EXISTS)",
            "CREATE UNIQUE INDEX",
            "REFRESH MATERIALIZED VIEW (blocking, not CONCURRENTLY)",
            "REVOKE on MV",
            "parity smoke (else RAISE → rollback)",
            "COMMIT",
            "session advisory unlock",
        ],
    }


def apply_write(conn: Any) -> dict[str, Any]:
    conn.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": LOCK_KEY})
    try:
        with conn.begin():
            if _relkind(conn, BAK) is not None:
                raise RuntimeError(f"CONTRACT: backup {BAK} already exists — refuse")

            kind = _relkind(conn, MV)
            if kind == "m":
                raise RuntimeError("already a materialized view — refuse re-entry")
            if kind == "r":
                conn.execute(text(f'ALTER TABLE public."{MV}" RENAME TO "{BAK}"'))
                if _index_exists(conn, UQ):
                    conn.execute(text(f'ALTER INDEX public."{UQ}" RENAME TO "{BAK_IDX}"'))
                _revoke_public_roles(conn, BAK)
            elif kind is not None:
                raise RuntimeError(f"unexpected relkind={kind!r} for {MV}")

            if _relkind(conn, MV) is not None:
                raise RuntimeError(f"{MV} still occupied after rename")

            conn.execute(text(_mv_sql_create_only()))
            conn.execute(text(_index_sql()))
            conn.execute(text(f'REFRESH MATERIALIZED VIEW public."{MV}"'))
            _revoke_public_roles(conn, MV)

            smoke = _parity_smoke(conn)
            if not smoke["ok"]:
                raise RuntimeError(f"parity smoke failed: {smoke}")
            return {"status": "applied", "parity": smoke}
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "rollback": "transaction_aborted"}
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": LOCK_KEY})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="execute canonicalize (OWNER ONLY)")
    args = parser.parse_args(argv)

    from app.db.session import get_session_factory

    sf = get_session_factory()
    with sf() as session:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            print("skip: not postgresql")
            return 0
        with bind.connect() as conn:
            if not args.write:
                plan = plan_dry_run(conn)
                print("DRY-RUN canonicalize plan:")
                for k, v in plan.items():
                    print(f"  {k}: {v}")
                if plan["backup_exists"]:
                    print("REFUSE preview: backup name already occupied")
                    return 1
                return 0

            result = apply_write(conn)
            print(result)
            return 0 if result.get("status") == "applied" else 1


if __name__ == "__main__":
    raise SystemExit(main())
