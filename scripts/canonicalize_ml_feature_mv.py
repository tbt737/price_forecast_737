"""Two-phase canonicalize: TABLE ``mv_ml_daily_features_wide`` → MATERIALIZED VIEW.

Phase A (candidate, no lock on production name):
  CREATE candidate MV → unique index → REVOKE → blocking REFRESH → parity.

Phase B (final refresh + short cutover):
  fact snapshot → REFRESH CONCURRENTLY candidate → re-check snapshot →
  short transaction: TABLE→backup, candidate→canonical, rename indexes.

Heavy REFRESH never runs inside the cutover transaction (avoids holding
AccessExclusiveLock for the full rebuild on small Postgres plans).

Dry-run by default (INV-7). ``--write`` is the sole production apply path.
``--rollback`` restores TABLE from backup after a successful cutover.
``--cleanup-candidate`` drops an orphan candidate (never drops backup).

Exit codes:
  0 — dry-run ok / write applied / rollback|cleanup done
  1 — refused or failed (canonical TABLE untouched on phase-A failure)
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
CAND = "mv_ml_daily_features_wide_cand"
BAK = "mv_ml_daily_features_wide_table_bak"
UQ = "uq_mv_ml_daily_features_wide"
CAND_UQ = "uq_mv_ml_daily_features_wide_cand"
BAK_IDX = "uq_mv_ml_daily_features_wide_table_bak"
LOCK_KEY = "ml_feature_view_canonicalize"

# Finite timeouts — never statement_timeout=0 (unbounded).
REFRESH_STATEMENT_TIMEOUT = "15min"
CUTOVER_LOCK_TIMEOUT = "3s"
CUTOVER_STATEMENT_TIMEOUT = "15s"

GEN_010 = _ROOT / "db" / "views" / "generated" / "010_mv_ml_daily_features_wide.sql"
IDX_011 = _ROOT / "db" / "views" / "011_indexes_ml_feature_views.sql"

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _qi(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return f'"{name}"'


def _mv_sql_create(name: str) -> str:
    raw = GEN_010.read_text(encoding="utf-8")
    body = re.sub(
        r"CREATE MATERIALIZED VIEW IF NOT EXISTS\s+\w+",
        f"CREATE MATERIALIZED VIEW {_qi(name)}",
        raw,
        count=1,
    )
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    create = next(s for s in stmts if "CREATE MATERIALIZED VIEW" in s)
    if "WITH NO DATA" not in create.upper():
        raise RuntimeError("generated MV SQL must be WITH NO DATA")
    return create


def _index_sql(index_name: str, relation: str) -> str:
    raw = IDX_011.read_text(encoding="utf-8")
    stmts = [s.strip() for s in raw.split(";") if s.strip() and "CREATE UNIQUE INDEX" in s]
    if not stmts:
        raise RuntimeError("011 unique index statement not found")
    # Rewrite target relation + index name; keep column list.
    return (
        f"CREATE UNIQUE INDEX {_qi(index_name)} "
        f"ON public.{_qi(relation)} (commodity_key, as_of_date)"
    )


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


def _relispopulated(conn: Any, name: str) -> bool | None:
    return conn.execute(
        text(
            """
            SELECT c.relispopulated
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


def _index_valid(conn: Any, name: str) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_class i
                  JOIN pg_namespace n ON n.oid = i.relnamespace
                  JOIN pg_index ix ON ix.indexrelid = i.oid
                  WHERE n.nspname = 'public' AND i.relname = :n
                    AND i.relkind = 'i' AND ix.indisunique AND ix.indisvalid
                )
                """
            ),
            {"n": name},
        ).scalar()
    )


def _revoke_public_roles(conn: Any, name: str) -> None:
    for role in ("PUBLIC", "anon", "authenticated"):
        conn.execute(text(f"REVOKE ALL ON TABLE public.{_qi(name)} FROM {role}"))


def _commit_if_open(conn: Any) -> None:
    if conn.in_transaction():
        conn.commit()


def fact_snapshot(conn: Any) -> dict[str, Any]:
    """Lightweight fingerprint of fact_price_daily for race detection."""
    row = conn.execute(
        text(
            """
            SELECT
              count(*)::bigint AS n_rows,
              coalesce(max(revision), 0)::bigint AS max_revision,
              max(price_date)::text AS max_price_date,
              coalesce(
                sum(hashtext(
                  commodity_key::text || '|' || price_date::text || '|' || revision::text
                )),
                0
              )::bigint AS grain_hash
            FROM fact_price_daily
            """
        )
    ).mappings().one()
    return {
        "n_rows": int(row["n_rows"]),
        "max_revision": int(row["max_revision"]),
        "max_price_date": row["max_price_date"],
        "grain_hash": int(row["grain_hash"]),
    }


def parity_relation(conn: Any, name: str, *, expect_index: str) -> dict[str, Any]:
    kind = _relkind(conn, name)
    populated = _relispopulated(conn, name) if kind == "m" else None
    rows = int(conn.execute(text(f"SELECT COUNT(*) FROM public.{_qi(name)}")).scalar_one())
    grain = int(
        conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM (
                  SELECT commodity_key, as_of_date
                  FROM public.{_qi(name)}
                  GROUP BY commodity_key, as_of_date
                  HAVING COUNT(*) > 1
                ) d
                """
            )
        ).scalar_one()
    )
    dmax = conn.execute(text(f"SELECT MAX(as_of_date) FROM public.{_qi(name)}")).scalar()
    n_comm = int(
        conn.execute(text(f"SELECT COUNT(DISTINCT commodity_key) FROM public.{_qi(name)}")).scalar_one()
    )
    has_uq = _index_exists(conn, expect_index)
    uq_valid = _index_valid(conn, expect_index) if has_uq else False
    ok = (
        kind == "m"
        and populated is True
        and grain == 0
        and has_uq
        and uq_valid
        and rows > 0
        and n_comm >= 1
    )
    return {
        "ok": ok,
        "name": name,
        "relkind": kind,
        "relispopulated": populated,
        "rows": rows,
        "duplicate_grains": grain,
        "max_as_of_date": None if dmax is None else str(dmax),
        "distinct_commodity_keys": n_comm,
        "unique_index": has_uq,
        "unique_index_valid": uq_valid,
        "expect_index": expect_index,
    }


def refuse_if_occupied(conn: Any) -> None:
    """Fail-closed before any DDL: candidate / backup must be free."""
    if _relkind(conn, CAND) is not None:
        raise RuntimeError(f"CONTRACT: candidate {CAND} already exists — refuse (stale orphan)")
    if _relkind(conn, BAK) is not None:
        raise RuntimeError(f"CONTRACT: backup {BAK} already exists — refuse")
    if _index_exists(conn, CAND_UQ):
        raise RuntimeError(f"CONTRACT: candidate index {CAND_UQ} already exists — refuse")
    if _index_exists(conn, BAK_IDX):
        raise RuntimeError(f"CONTRACT: backup index {BAK_IDX} already exists — refuse")


def build_candidate(conn: Any) -> None:
    """Create + index + revoke + initial blocking refresh. Does not touch MV name."""
    refuse_if_occupied(conn)
    kind = _relkind(conn, MV)
    if kind == "m":
        raise RuntimeError("already a materialized view — refuse re-entry")
    if kind not in ("r", None):
        raise RuntimeError(f"unexpected relkind={kind!r} for {MV}")

    conn.execute(text(f"SET statement_timeout = '{REFRESH_STATEMENT_TIMEOUT}'"))
    try:
        conn.execute(text(_mv_sql_create(CAND)))
        _commit_if_open(conn)
        conn.execute(text(_index_sql(CAND_UQ, CAND)))
        _commit_if_open(conn)
        _revoke_public_roles(conn, CAND)
        _commit_if_open(conn)
        conn.execute(text(f"REFRESH MATERIALIZED VIEW public.{_qi(CAND)}"))
        _commit_if_open(conn)
    except Exception:
        # Best-effort orphan cleanup so a failed build does not block retry;
        # never touches the canonical TABLE name.
        _commit_if_open(conn)
        cleanup_candidate(conn, missing_ok=True)
        raise
    finally:
        conn.execute(text("SET statement_timeout = DEFAULT"))
        _commit_if_open(conn)


def final_refresh_candidate(conn: Any) -> None:
    conn.execute(text(f"SET statement_timeout = '{REFRESH_STATEMENT_TIMEOUT}'"))
    try:
        conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY public.{_qi(CAND)}"))
        _commit_if_open(conn)
    finally:
        conn.execute(text("SET statement_timeout = DEFAULT"))
        _commit_if_open(conn)


def cutover(conn: Any, expected_snap: dict[str, Any]) -> dict[str, Any]:
    """Short rename-only transaction. No REFRESH inside."""
    conn.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": LOCK_KEY})
    _commit_if_open(conn)
    try:
        with conn.begin():
            conn.execute(text(f"SET LOCAL lock_timeout = '{CUTOVER_LOCK_TIMEOUT}'"))
            conn.execute(text(f"SET LOCAL statement_timeout = '{CUTOVER_STATEMENT_TIMEOUT}'"))

            snap_now = fact_snapshot(conn)
            if snap_now != expected_snap:
                raise RuntimeError(
                    f"CONTRACT: fact snapshot raced before cutover: {snap_now} != {expected_snap}"
                )

            if _relkind(conn, BAK) is not None:
                raise RuntimeError(f"CONTRACT: backup {BAK} appeared before cutover — refuse")
            if _relkind(conn, CAND) != "m":
                raise RuntimeError(f"CONTRACT: candidate {CAND} missing or not matview")
            if not _index_valid(conn, CAND_UQ):
                raise RuntimeError(f"CONTRACT: candidate unique index {CAND_UQ} missing/invalid")

            kind = _relkind(conn, MV)
            if kind == "m":
                raise RuntimeError("already a materialized view — refuse cutover")
            if kind == "r":
                conn.execute(text(f"ALTER TABLE public.{_qi(MV)} RENAME TO {_qi(BAK)}"))
                if _index_exists(conn, UQ):
                    conn.execute(text(f"ALTER INDEX public.{_qi(UQ)} RENAME TO {_qi(BAK_IDX)}"))
                _revoke_public_roles(conn, BAK)
            elif kind is not None:
                raise RuntimeError(f"unexpected relkind={kind!r} for {MV}")

            if _relkind(conn, MV) is not None:
                raise RuntimeError(f"{MV} still occupied after table rename")

            conn.execute(text(f"ALTER MATERIALIZED VIEW public.{_qi(CAND)} RENAME TO {_qi(MV)}"))
            conn.execute(text(f"ALTER INDEX public.{_qi(CAND_UQ)} RENAME TO {_qi(UQ)}"))
            _revoke_public_roles(conn, MV)

            smoke = parity_relation(conn, MV, expect_index=UQ)
            if not smoke["ok"]:
                raise RuntimeError(f"cutover parity failed: {smoke}")
            return {"status": "applied", "parity": smoke, "fact_snapshot": expected_snap}
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": LOCK_KEY})
        _commit_if_open(conn)


def apply_write(conn: Any) -> dict[str, Any]:
    """Full two-phase apply. Phase-A failure leaves canonical TABLE intact."""
    build_candidate(conn)
    parity = parity_relation(conn, CAND, expect_index=CAND_UQ)
    if not parity["ok"]:
        cleanup_candidate(conn, missing_ok=True)
        return {"status": "failed", "error": f"candidate parity failed: {parity}", "phase": "parity"}

    snap = fact_snapshot(conn)
    final_refresh_candidate(conn)
    snap_after = fact_snapshot(conn)
    if snap_after != snap:
        # Candidate may be slightly newer; leave it for inspection — do not cut over.
        return {
            "status": "failed",
            "error": f"fact snapshot changed during final refresh: {snap} → {snap_after}",
            "phase": "final_refresh",
            "candidate_left": CAND,
        }

    try:
        result = cutover(conn, expected_snap=snap)
        return result
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "phase": "cutover",
            "candidate_left": CAND if _relkind(conn, CAND) is not None else None,
            "backup_left": BAK if _relkind(conn, BAK) is not None else None,
            "note": "cutover aborted; use --rollback if backup exists, --cleanup-candidate if orphan",
        }


def rollback_cutover(conn: Any) -> dict[str, Any]:
    """Restore TABLE from backup; drop canonical matview. Does NOT drop backup on failure mid-way."""
    conn.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": LOCK_KEY})
    _commit_if_open(conn)
    try:
        with conn.begin():
            conn.execute(text(f"SET LOCAL lock_timeout = '{CUTOVER_LOCK_TIMEOUT}'"))
            bak_kind = _relkind(conn, BAK)
            if bak_kind != "r":
                raise RuntimeError(f"rollback: backup {BAK} missing or not a table (kind={bak_kind!r})")

            mv_kind = _relkind(conn, MV)
            if mv_kind == "m":
                conn.execute(text(f"DROP MATERIALIZED VIEW public.{_qi(MV)}"))
            elif mv_kind is not None:
                raise RuntimeError(f"rollback: {MV} unexpected relkind={mv_kind!r}")

            conn.execute(text(f"ALTER TABLE public.{_qi(BAK)} RENAME TO {_qi(MV)}"))
            if _index_exists(conn, BAK_IDX):
                conn.execute(text(f"ALTER INDEX public.{_qi(BAK_IDX)} RENAME TO {_qi(UQ)}"))
            return {"status": "rolled_back", "restored": MV, "backup_dropped": False}
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": LOCK_KEY})
        _commit_if_open(conn)


def cleanup_candidate(conn: Any, *, missing_ok: bool = False) -> dict[str, Any]:
    """Drop orphan candidate MV (+ its index). Never drops backup or canonical name."""
    kind = _relkind(conn, CAND)
    if kind is None:
        if missing_ok:
            if _index_exists(conn, CAND_UQ):
                conn.execute(text(f"DROP INDEX IF EXISTS public.{_qi(CAND_UQ)}"))
                _commit_if_open(conn)
            return {"status": "cleanup_noop", "candidate": CAND}
        raise RuntimeError(f"cleanup: candidate {CAND} not found")
    if kind != "m":
        raise RuntimeError(f"cleanup: {CAND} unexpected relkind={kind!r} — refuse")
    conn.execute(text(f"DROP MATERIALIZED VIEW public.{_qi(CAND)}"))
    _commit_if_open(conn)
    # Index drops with the matview; belt-and-suspenders for a leftover name.
    if _index_exists(conn, CAND_UQ):
        conn.execute(text(f"DROP INDEX IF EXISTS public.{_qi(CAND_UQ)}"))
        _commit_if_open(conn)
    return {"status": "cleaned", "dropped": CAND, "backup_untouched": True}


def plan_dry_run(conn: Any) -> dict[str, Any]:
    return {
        "mode": "two_phase_cutover",
        "lock": f"pg_advisory_lock(hashtext('{LOCK_KEY}')) — cutover/rollback only",
        "refresh_timeout": REFRESH_STATEMENT_TIMEOUT,
        "cutover_lock_timeout": CUTOVER_LOCK_TIMEOUT,
        "mv_relkind": _relkind(conn, MV),
        "candidate_exists": _relkind(conn, CAND) is not None,
        "backup_exists": _relkind(conn, BAK) is not None,
        "create_sql_head": _mv_sql_create(CAND).splitlines()[0],
        "index_sql": _index_sql(CAND_UQ, CAND),
        "steps": [
            "fail-closed if candidate/backup names exist",
            "CREATE MATERIALIZED VIEW candidate WITH NO DATA (production name untouched)",
            "CREATE UNIQUE INDEX on candidate + REVOKE",
            f"REFRESH MATERIALIZED VIEW candidate (blocking, timeout={REFRESH_STATEMENT_TIMEOUT})",
            "parity on candidate",
            "fact_price_daily snapshot",
            "REFRESH MATERIALIZED VIEW CONCURRENTLY candidate",
            "re-check fact snapshot (refuse cutover on race)",
            f"short cutover txn (lock_timeout={CUTOVER_LOCK_TIMEOUT}): "
            "TABLE→backup, candidate→canonical, rename indexes — no REFRESH",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="execute two-phase canonicalize (OWNER ONLY)")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="restore TABLE from backup after cutover (OWNER ONLY; does not drop backup mid-flight)",
    )
    parser.add_argument(
        "--cleanup-candidate",
        action="store_true",
        help="drop orphan candidate MV only (never drops backup)",
    )
    args = parser.parse_args(argv)
    modes = sum(bool(x) for x in (args.write, args.rollback, args.cleanup_candidate))
    if modes > 1:
        print("REFUSE: use only one of --write / --rollback / --cleanup-candidate")
        return 1

    from app.db.session import get_session_factory

    sf = get_session_factory()
    with sf() as session:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            print("skip: not postgresql")
            return 0
        with bind.connect() as conn:
            if args.cleanup_candidate:
                try:
                    result = cleanup_candidate(conn)
                except Exception as exc:
                    print({"status": "failed", "error": str(exc)})
                    return 1
                print(result)
                return 0

            if args.rollback:
                try:
                    result = rollback_cutover(conn)
                except Exception as exc:
                    print({"status": "failed", "error": str(exc)})
                    return 1
                print(result)
                return 0

            if not args.write:
                plan = plan_dry_run(conn)
                print("DRY-RUN two-phase canonicalize plan:")
                for k, v in plan.items():
                    print(f"  {k}: {v}")
                if plan["candidate_exists"] or plan["backup_exists"]:
                    print("REFUSE preview: candidate or backup name already occupied")
                    return 1
                return 0

            try:
                refuse_if_occupied(conn)
            except Exception as exc:
                print({"status": "failed", "error": str(exc), "phase": "precheck"})
                return 1

            result = apply_write(conn)
            print(result)
            return 0 if result.get("status") == "applied" else 1


if __name__ == "__main__":
    raise SystemExit(main())
