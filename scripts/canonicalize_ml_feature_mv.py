"""Two-phase canonicalize with an operator boundary between prepare and cutover.

``--prepare-candidate`` (OWNER):
  advisory lock → create candidate MV → index → REVOKE → blocking REFRESH →
  parity → **stop**. Never renames the canonical TABLE/MV name.

``--cutover`` (OWNER, separate approval):
  advisory lock → revalidate candidate → full-fact snapshot →
  REFRESH CONCURRENTLY → re-check snapshot → short rename txn
  (TABLE→backup, candidate→canonical). No REFRESH inside the rename txn.

Production must **not** use a one-shot ``--write``; that flag is rejected.

Also: ``--rollback``, ``--cleanup-candidate``.
Finite refresh timeout (default 30min; ``--refresh-timeout-min`` bounded).

Exit codes:
  0 — dry-run ok / mode succeeded
  1 — refused or failed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable
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
DEFAULT_REFRESH_TIMEOUT_MIN = 30
MIN_REFRESH_TIMEOUT_MIN = 5
MAX_REFRESH_TIMEOUT_MIN = 120
CUTOVER_LOCK_TIMEOUT = "3s"
CUTOVER_STATEMENT_TIMEOUT = "15s"

# Six fact families the wide MV / feature path can read (ARCHITECTURE fact set).
FACT_FAMILY_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "fact_price_daily",
        "price_date",
        "commodity_key::text || '|' || coalesce(market_instrument_key::text, '') || '|' "
        "|| price_date::text || '|' || revision::text",
    ),
    (
        "fact_weather_daily",
        "weather_date",
        "commodity_key::text || '|' || region_key::text || '|' || weather_date::text || '|' "
        "|| metric_code || '|' || revision::text",
    ),
    (
        "fact_macro_daily",
        "macro_date",
        "coalesce(commodity_key::text, '') || '|' || macro_date::text || '|' "
        "|| indicator_code || '|' || revision::text",
    ),
    (
        "fact_logistics_periodic",
        "period_end",
        "coalesce(commodity_key::text, '') || '|' || coalesce(region_key::text, '') || '|' "
        "|| period_start::text || '|' || period_end::text || '|' || indicator_code || '|' "
        "|| revision::text",
    ),
    (
        "fact_supply_demand_periodic",
        "period_end",
        "commodity_key::text || '|' || coalesce(region_key::text, '') || '|' "
        "|| period_start::text || '|' || period_end::text || '|' || metric_code || '|' "
        "|| revision::text",
    ),
    (
        "fact_event_risk",
        "event_date",
        "coalesce(commodity_key::text, '') || '|' || coalesce(region_key::text, '') || '|' "
        "|| event_date::text || '|' || metric_code || '|' || revision::text",
    ),
)

GEN_010 = _ROOT / "db" / "views" / "generated" / "010_mv_ml_daily_features_wide.sql"
IDX_011 = _ROOT / "db" / "views" / "011_indexes_ml_feature_views.sql"

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _qi(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return f'"{name}"'


def refresh_timeout_sql(minutes: int) -> str:
    if minutes < MIN_REFRESH_TIMEOUT_MIN or minutes > MAX_REFRESH_TIMEOUT_MIN:
        raise ValueError(
            f"refresh-timeout-min must be in "
            f"[{MIN_REFRESH_TIMEOUT_MIN}, {MAX_REFRESH_TIMEOUT_MIN}], got {minutes}"
        )
    return f"{minutes}min"


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


def _advisory_lock(conn: Any) -> None:
    conn.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": LOCK_KEY})
    _commit_if_open(conn)


def _advisory_unlock(conn: Any) -> None:
    conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": LOCK_KEY})
    _commit_if_open(conn)


def with_session_lock(conn: Any, fn: Callable[[], Any]) -> Any:
    _advisory_lock(conn)
    try:
        return fn()
    finally:
        _advisory_unlock(conn)


def fact_snapshot(conn: Any) -> dict[str, Any]:
    """Fingerprint all six fact families the feature MV can consume."""
    families: dict[str, dict[str, Any]] = {}
    for table, date_col, grain_expr in FACT_FAMILY_SPECS:
        if not _IDENT.match(table) or not _IDENT.match(date_col):
            raise ValueError(f"unsafe fact family spec: {table}.{date_col}")
        row = conn.execute(
            text(
                f"""
                SELECT
                  count(*)::bigint AS n_rows,
                  coalesce(max(revision), 0)::bigint AS max_revision,
                  max({date_col})::text AS max_date,
                  coalesce(sum(hashtext({grain_expr})), 0)::bigint AS grain_hash
                FROM {table}
                """
            )
        ).mappings().one()
        families[table] = {
            "n_rows": int(row["n_rows"]),
            "max_revision": int(row["max_revision"]),
            "max_date": row["max_date"],
            "grain_hash": int(row["grain_hash"]),
        }
    payload = json.dumps(families, sort_keys=True, separators=(",", ":"))
    return {
        "families": families,
        "combined_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
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
    """Fail-closed before prepare DDL: candidate / backup must be free."""
    if _relkind(conn, CAND) is not None:
        raise RuntimeError(f"CONTRACT: candidate {CAND} already exists — refuse (stale orphan)")
    if _relkind(conn, BAK) is not None:
        raise RuntimeError(f"CONTRACT: backup {BAK} already exists — refuse")
    if _index_exists(conn, CAND_UQ):
        raise RuntimeError(f"CONTRACT: candidate index {CAND_UQ} already exists — refuse")
    if _index_exists(conn, BAK_IDX):
        raise RuntimeError(f"CONTRACT: backup index {BAK_IDX} already exists — refuse")


def build_candidate(conn: Any, *, refresh_timeout: str) -> None:
    """Create + index + revoke + initial blocking refresh. Does not rename canonical."""
    refuse_if_occupied(conn)
    kind = _relkind(conn, MV)
    if kind == "m":
        raise RuntimeError("already a materialized view — refuse re-entry")
    if kind not in ("r", None):
        raise RuntimeError(f"unexpected relkind={kind!r} for {MV}")

    conn.execute(text(f"SET statement_timeout = '{refresh_timeout}'"))
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
        _commit_if_open(conn)
        cleanup_candidate(conn, missing_ok=True)
        raise
    finally:
        conn.execute(text("SET statement_timeout = DEFAULT"))
        _commit_if_open(conn)


def final_refresh_candidate(conn: Any, *, refresh_timeout: str) -> None:
    conn.execute(text(f"SET statement_timeout = '{refresh_timeout}'"))
    try:
        conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY public.{_qi(CAND)}"))
        _commit_if_open(conn)
    finally:
        conn.execute(text("SET statement_timeout = DEFAULT"))
        _commit_if_open(conn)


def validate_candidate_for_cutover(conn: Any) -> dict[str, Any]:
    """Refuse missing / unpopulated / stale / parity-fail candidates."""
    kind = _relkind(conn, CAND)
    if kind is None:
        raise RuntimeError(f"CONTRACT: candidate {CAND} missing — refuse cutover")
    if kind != "m":
        raise RuntimeError(f"CONTRACT: candidate {CAND} unexpected relkind={kind!r}")
    populated = _relispopulated(conn, CAND)
    if populated is not True:
        raise RuntimeError(f"CONTRACT: candidate {CAND} unpopulated — refuse cutover")
    if not _index_valid(conn, CAND_UQ):
        raise RuntimeError(f"CONTRACT: candidate unique index {CAND_UQ} missing/invalid")
    parity = parity_relation(conn, CAND, expect_index=CAND_UQ)
    if not parity["ok"]:
        raise RuntimeError(f"CONTRACT: candidate parity fail — refuse cutover: {parity}")
    # Stale: populated flag true but empty / no as_of coverage after prepare.
    if parity["rows"] <= 0 or parity["max_as_of_date"] is None:
        raise RuntimeError(f"CONTRACT: candidate {CAND} stale (empty coverage) — refuse cutover")
    return parity


def cutover_rename(conn: Any, expected_snap: dict[str, Any]) -> dict[str, Any]:
    """Short rename-only transaction. Caller must hold session advisory lock. No REFRESH."""
    with conn.begin():
        conn.execute(text(f"SET LOCAL lock_timeout = '{CUTOVER_LOCK_TIMEOUT}'"))
        conn.execute(text(f"SET LOCAL statement_timeout = '{CUTOVER_STATEMENT_TIMEOUT}'"))

        snap_now = fact_snapshot(conn)
        if snap_now != expected_snap:
            raise RuntimeError(
                f"CONTRACT: full-fact fingerprint raced before cutover: "
                f"{snap_now['combined_sha256']} != {expected_snap['combined_sha256']}"
            )

        if _relkind(conn, BAK) is not None:
            raise RuntimeError(f"CONTRACT: backup {BAK} appeared before cutover — refuse")
        validate_candidate_for_cutover(conn)

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
        return {
            "status": "cutover_applied",
            "parity": smoke,
            "fact_snapshot_sha256": expected_snap["combined_sha256"],
        }


def prepare_candidate(conn: Any, *, refresh_timeout: str) -> dict[str, Any]:
    """Build + refresh + parity; stop. Never renames canonical objects."""

    def _body() -> dict[str, Any]:
        build_candidate(conn, refresh_timeout=refresh_timeout)
        # Invariant: prepare must not have renamed the production name.
        if _relkind(conn, BAK) is not None:
            raise RuntimeError("CONTRACT: prepare created backup — abort (canonical rename leaked)")
        if _relkind(conn, MV) == "m":
            raise RuntimeError("CONTRACT: prepare turned canonical into matview — abort")
        parity = parity_relation(conn, CAND, expect_index=CAND_UQ)
        if not parity["ok"]:
            cleanup_candidate(conn, missing_ok=True)
            return {
                "status": "failed",
                "error": f"candidate parity failed: {parity}",
                "phase": "prepare_parity",
            }
        return {
            "status": "prepared",
            "candidate": CAND,
            "parity": parity,
            "refresh_timeout": refresh_timeout,
            "canonical_untouched": True,
            "next": "operator approval required before --cutover",
        }

    return with_session_lock(conn, _body)


def run_cutover(conn: Any, *, refresh_timeout: str) -> dict[str, Any]:
    """Revalidate → final concurrent refresh → snapshot gate → short rename."""

    def _body() -> dict[str, Any]:
        try:
            validate_candidate_for_cutover(conn)
        except Exception as exc:
            return {"status": "failed", "error": str(exc), "phase": "revalidate"}

        snap = fact_snapshot(conn)
        final_refresh_candidate(conn, refresh_timeout=refresh_timeout)
        snap_after = fact_snapshot(conn)
        if snap_after != snap:
            return {
                "status": "failed",
                "error": (
                    "full-fact fingerprint changed during final refresh: "
                    f"{snap['combined_sha256']} → {snap_after['combined_sha256']}"
                ),
                "phase": "final_refresh",
                "candidate_left": CAND,
            }

        try:
            # Revalidate after refresh (stale/empty after concurrent refresh).
            validate_candidate_for_cutover(conn)
            return cutover_rename(conn, expected_snap=snap)
        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "phase": "cutover",
                "candidate_left": CAND if _relkind(conn, CAND) is not None else None,
                "backup_left": BAK if _relkind(conn, BAK) is not None else None,
                "note": "use --rollback if backup exists, --cleanup-candidate if orphan",
            }

    return with_session_lock(conn, _body)


def rollback_cutover(conn: Any) -> dict[str, Any]:
    """Restore TABLE from backup; drop canonical matview."""

    def _body() -> dict[str, Any]:
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

    return with_session_lock(conn, _body)


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
    if _index_exists(conn, CAND_UQ):
        conn.execute(text(f"DROP INDEX IF EXISTS public.{_qi(CAND_UQ)}"))
        _commit_if_open(conn)
    return {"status": "cleaned", "dropped": CAND, "backup_untouched": True}


def plan_dry_run(conn: Any, *, refresh_timeout: str) -> dict[str, Any]:
    return {
        "mode": "two_phase_operator_boundary",
        "commands": {
            "prepare": "--prepare-candidate",
            "cutover": "--cutover (separate approval)",
            "rollback": "--rollback",
            "cleanup": "--cleanup-candidate",
        },
        "lock": f"pg_advisory_lock(hashtext('{LOCK_KEY}')) — prepare AND cutover",
        "refresh_timeout": refresh_timeout,
        "cutover_lock_timeout": CUTOVER_LOCK_TIMEOUT,
        "fact_families": [t for t, _, _ in FACT_FAMILY_SPECS],
        "mv_relkind": _relkind(conn, MV),
        "candidate_exists": _relkind(conn, CAND) is not None,
        "backup_exists": _relkind(conn, BAK) is not None,
        "create_sql_head": _mv_sql_create(CAND).splitlines()[0],
        "index_sql": _index_sql(CAND_UQ, CAND),
        "prepare_steps": [
            "session advisory lock",
            "fail-closed if candidate/backup names exist",
            "CREATE MATERIALIZED VIEW candidate WITH NO DATA (canonical untouched)",
            "CREATE UNIQUE INDEX + REVOKE",
            f"REFRESH MATERIALIZED VIEW candidate (blocking, timeout={refresh_timeout})",
            "parity on candidate → STOP for operator approval",
        ],
        "cutover_steps": [
            "session advisory lock",
            "revalidate candidate (missing/unpopulated/stale/parity)",
            "full 6-family fact snapshot",
            f"REFRESH MATERIALIZED VIEW CONCURRENTLY candidate (timeout={refresh_timeout})",
            "re-check full-fact fingerprint",
            f"short rename txn (lock_timeout={CUTOVER_LOCK_TIMEOUT}) — no REFRESH",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare-candidate",
        action="store_true",
        help="build/refresh/parity candidate then STOP (OWNER; no canonical rename)",
    )
    parser.add_argument(
        "--cutover",
        action="store_true",
        help="revalidate + final refresh + short rename (OWNER; separate approval)",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="restore TABLE from backup after cutover",
    )
    parser.add_argument(
        "--cleanup-candidate",
        action="store_true",
        help="drop orphan candidate MV only (never drops backup)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=argparse.SUPPRESS,  # rejected — kept only to fail closed on old runbooks
    )
    parser.add_argument(
        "--refresh-timeout-min",
        type=int,
        default=DEFAULT_REFRESH_TIMEOUT_MIN,
        help=(
            f"finite REFRESH statement_timeout in minutes "
            f"[{MIN_REFRESH_TIMEOUT_MIN}..{MAX_REFRESH_TIMEOUT_MIN}]; "
            f"default {DEFAULT_REFRESH_TIMEOUT_MIN}"
        ),
    )
    args = parser.parse_args(argv)

    if args.write:
        print(
            "REFUSE: --write is removed. Use --prepare-candidate, then separately "
            "--cutover after operator approval."
        )
        return 1

    modes = sum(
        bool(x)
        for x in (args.prepare_candidate, args.cutover, args.rollback, args.cleanup_candidate)
    )
    if modes > 1:
        print(
            "REFUSE: use only one of --prepare-candidate / --cutover / "
            "--rollback / --cleanup-candidate"
        )
        return 1

    try:
        refresh_timeout = refresh_timeout_sql(args.refresh_timeout_min)
    except ValueError as exc:
        print({"status": "failed", "error": str(exc)})
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

            if args.prepare_candidate:
                result = prepare_candidate(conn, refresh_timeout=refresh_timeout)
                print(result)
                return 0 if result.get("status") == "prepared" else 1

            if args.cutover:
                result = run_cutover(conn, refresh_timeout=refresh_timeout)
                print(result)
                return 0 if result.get("status") == "cutover_applied" else 1

            plan = plan_dry_run(conn, refresh_timeout=refresh_timeout)
            print("DRY-RUN two-phase plan (operator boundary):")
            for k, v in plan.items():
                print(f"  {k}: {v}")
            if plan["candidate_exists"] or plan["backup_exists"]:
                print("NOTE: candidate or backup name occupied — prepare will refuse until cleaned")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
