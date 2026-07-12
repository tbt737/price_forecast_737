"""Unit tests for prepare/cutover operator-boundary canonicalize runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import scripts.canonicalize_ml_feature_mv as runner

REPO = Path(__file__).resolve().parents[2]


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def mappings(self) -> Any:
        return self

    def one(self) -> Any:
        return self._value


class FakeConn:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = list(responses or [])
        self.executed: list[str] = []
        self._in_txn = False

    def in_transaction(self) -> bool:
        return self._in_txn

    def commit(self) -> None:
        self._in_txn = False

    def begin(self) -> Any:
        self._in_txn = True
        conn = self

        class _Ctx:
            def __enter__(self_inner) -> FakeConn:
                return conn

            def __exit__(self_inner, exc_type: Any, exc: Any, tb: Any) -> bool:
                conn._in_txn = False
                return False

        return _Ctx()

    def execute(self, statement: Any, params: Any = None) -> _ScalarResult:
        sql = statement.text if hasattr(statement, "text") else str(statement)
        self.executed.append(sql)
        self._in_txn = True
        if not self.responses:
            raise AssertionError(f"unexpected execute: {sql[:160]}")
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return _ScalarResult(value)


def _snap(n: int = 1) -> dict[str, Any]:
    families = {
        name: {
            "n_rows": n,
            "max_revision": 0,
            "max_date": "2026-07-10",
            "grain_hash": n * 10,
        }
        for name, _, _ in runner.FACT_FAMILY_SPECS
    }
    import hashlib
    import json

    payload = json.dumps(families, sort_keys=True, separators=(",", ":"))
    return {
        "families": families,
        "combined_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def test_write_flag_refused() -> None:
    assert runner.main(["--write"]) == 1


def test_modes_mutually_exclusive() -> None:
    assert runner.main(["--prepare-candidate", "--cutover"]) == 1


def test_refresh_timeout_bounds() -> None:
    assert runner.refresh_timeout_sql(30) == "30min"
    with pytest.raises(ValueError):
        runner.refresh_timeout_sql(4)
    with pytest.raises(ValueError):
        runner.refresh_timeout_sql(121)


def test_fact_snapshot_covers_six_families() -> None:
    names = [t for t, _, _ in runner.FACT_FAMILY_SPECS]
    assert names == [
        "fact_price_daily",
        "fact_weather_daily",
        "fact_macro_daily",
        "fact_logistics_periodic",
        "fact_supply_demand_periodic",
        "fact_event_risk",
    ]
    # One response mapping per family
    fam_row = {
        "n_rows": 1,
        "max_revision": 0,
        "max_date": "2026-07-01",
        "grain_hash": 42,
    }
    conn = FakeConn(responses=[fam_row] * 6)
    snap = runner.fact_snapshot(conn)
    assert set(snap["families"]) == set(names)
    assert len(snap["combined_sha256"]) == 64
    assert all(t in "\n".join(conn.executed) for t in names)


def test_refuse_stale_candidate_name() -> None:
    conn = FakeConn(responses=["m"])
    with pytest.raises(RuntimeError, match="candidate .* already exists"):
        runner.refuse_if_occupied(conn)


def test_prepare_uses_lock_and_never_renames_canonical() -> None:
    conn = FakeConn()
    order: list[str] = []

    def lock_wrap(c: Any, fn: Any) -> Any:
        order.append("lock")
        # simulate lock/unlock executes already handled by real with_session_lock —
        # we patch with_session_lock itself
        return fn()

    with (
        patch.object(runner, "with_session_lock", side_effect=lock_wrap),
        patch.object(runner, "build_candidate") as build,
        patch.object(runner, "_relkind", side_effect=["r", "r"]),  # bak check None path: BAK, MV
        patch.object(
            runner,
            "parity_relation",
            return_value={"ok": True, "rows": 10, "max_as_of_date": "2026-07-10"},
        ),
    ):
        # prepare_candidate body checks _relkind(BAK) and _relkind(MV)
        # Fix side_effect: BAK=None, MV='r' (still table)
        with patch.object(runner, "_relkind", side_effect=[None, "r"]):
            result = runner.prepare_candidate(conn, refresh_timeout="30min")

    assert result["status"] == "prepared"
    assert result["canonical_untouched"] is True
    build.assert_called_once()
    assert order == ["lock"]
    joined = "\n".join(conn.executed)
    assert f'RENAME TO "{runner.BAK}"' not in joined
    assert "ALTER TABLE" not in joined


def test_prepare_build_failure_cleans_orphan() -> None:
    conn = FakeConn(
        responses=[
            None,  # lock
            None,
            None,
            False,
            False,  # refuse
            "r",
            None,  # create
            None,  # index
            None,
            None,
            None,  # revoke
            RuntimeError("refresh blew up"),
            None,  # SET DEFAULT
            None,  # unlock
        ]
    )
    cleaned: list[bool] = []

    def _cleanup(c: Any, *, missing_ok: bool = False) -> dict[str, Any]:
        cleaned.append(missing_ok)
        return {"status": "cleaned"}

    with patch.object(runner, "cleanup_candidate", side_effect=_cleanup):
        with pytest.raises(RuntimeError, match="refresh blew up"):
            runner.prepare_candidate(conn, refresh_timeout="30min")

    assert cleaned == [True]
    sql = "\n".join(conn.executed)
    assert "pg_advisory_lock" in sql
    assert "pg_advisory_unlock" in sql
    assert "30min" in sql
    assert "statement_timeout = 0" not in sql
    assert f'ALTER TABLE public."{runner.MV}"' not in sql


def test_cutover_refuses_missing_candidate() -> None:
    conn = FakeConn(responses=[None, None])  # lock + unlock
    with patch.object(runner, "validate_candidate_for_cutover", side_effect=RuntimeError("missing")):
        # Actually run_cutover calls validate inside body after lock
        pass
    conn = FakeConn(responses=[None, None])
    with patch.object(
        runner,
        "validate_candidate_for_cutover",
        side_effect=RuntimeError("CONTRACT: candidate missing"),
    ):
        result = runner.run_cutover(conn, refresh_timeout="30min")
    assert result["status"] == "failed"
    assert result["phase"] == "revalidate"
    assert "missing" in result["error"]


def test_validate_candidate_unpopulated() -> None:
    with (
        patch.object(runner, "_relkind", return_value="m"),
        patch.object(runner, "_relispopulated", return_value=False),
    ):
        with pytest.raises(RuntimeError, match="unpopulated"):
            runner.validate_candidate_for_cutover(FakeConn())


def test_validate_candidate_stale_empty() -> None:
    with (
        patch.object(runner, "_relkind", return_value="m"),
        patch.object(runner, "_relispopulated", return_value=True),
        patch.object(runner, "_index_valid", return_value=True),
        patch.object(
            runner,
            "parity_relation",
            return_value={
                "ok": True,
                "rows": 0,
                "max_as_of_date": None,
            },
        ),
    ):
        with pytest.raises(RuntimeError, match="stale"):
            runner.validate_candidate_for_cutover(FakeConn())


def test_cutover_refuses_fact_fingerprint_race() -> None:
    snap_a = _snap(1)
    snap_b = _snap(2)
    conn = FakeConn(responses=[None, None])  # lock unlock around body

    with (
        patch.object(runner, "validate_candidate_for_cutover", return_value={"ok": True}),
        patch.object(runner, "fact_snapshot", side_effect=[snap_a, snap_b]),
        patch.object(runner, "final_refresh_candidate") as final_ref,
        patch.object(runner, "cutover_rename") as cut,
    ):
        result = runner.run_cutover(conn, refresh_timeout="30min")

    assert result["status"] == "failed"
    assert result["phase"] == "final_refresh"
    assert "fingerprint changed" in result["error"]
    final_ref.assert_called_once()
    cut.assert_not_called()


def test_cutover_rename_has_no_refresh_and_short_lock() -> None:
    snap = _snap(3)
    # SET LOCAL x2, ALTER TABLE, ALTER INDEX, ALTER MV, ALTER INDEX
    conn = FakeConn(responses=[None] * 6)
    relkinds = iter([None, "r", None])  # bak via validate patched; inside: bak, mv, after rename

    with (
        patch.object(runner, "fact_snapshot", return_value=snap),
        patch.object(runner, "validate_candidate_for_cutover", return_value={"ok": True}),
        patch.object(runner, "_relkind", side_effect=lambda _c, n: next(relkinds)),
        patch.object(runner, "_index_exists", return_value=True),
        patch.object(runner, "_revoke_public_roles"),
        patch.object(runner, "parity_relation", return_value={"ok": True, "relkind": "m", "rows": 1}),
    ):
        out = runner.cutover_rename(conn, expected_snap=snap)

    assert out["status"] == "cutover_applied"
    joined = "\n".join(conn.executed)
    assert "REFRESH MATERIALIZED VIEW" not in joined
    assert f"lock_timeout = '{runner.CUTOVER_LOCK_TIMEOUT}'" in joined
    assert f'RENAME TO "{runner.BAK}"' in joined


def test_rollback_and_cleanup_invariants() -> None:
    conn = FakeConn(responses=[None, None, None, None, None, None])  # lock, begin SETs/DDL, unlock
    # rollback: lock, begin+SET, DROP, RENAME, RENAME idx, unlock = need careful count
    conn = FakeConn(responses=[None] * 8)
    with (
        patch.object(runner, "_relkind", side_effect=["r", "m"]),
        patch.object(runner, "_index_exists", return_value=True),
    ):
        result = runner.rollback_cutover(conn)
    assert result["backup_dropped"] is False

    conn2 = FakeConn(responses=["m", None])
    with patch.object(runner, "_index_exists", return_value=False):
        cleaned = runner.cleanup_candidate(conn2)
    assert cleaned["backup_untouched"] is True
    assert runner.BAK not in "\n".join(conn2.executed)


def test_source_invariants() -> None:
    src = (REPO / "scripts" / "canonicalize_ml_feature_mv.py").read_text(encoding="utf-8")
    assert "--prepare-candidate" in src
    assert "--cutover" in src
    assert "statement_timeout = 0" not in src
    assert "DEFAULT_REFRESH_TIMEOUT_MIN = 30" in src
    assert "fact_event_risk" in src
    assert "fact_supply_demand_periodic" in src
    assert "REFUSE: --write is removed" in src or "write is removed" in src
