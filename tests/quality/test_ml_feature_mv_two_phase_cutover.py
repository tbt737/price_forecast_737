"""Unit tests for two-phase ML feature MV canonicalize runner."""

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
    """Minimal connection stub: scripted execute results + recorded SQL."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = list(responses or [])
        self.executed: list[str] = []
        self._in_txn = False
        self.begun = 0

    def in_transaction(self) -> bool:
        return self._in_txn

    def commit(self) -> None:
        self._in_txn = False

    def begin(self) -> Any:
        self.begun += 1
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


def test_refuse_stale_candidate() -> None:
    conn = FakeConn(responses=["m"])
    with pytest.raises(RuntimeError, match="candidate .* already exists"):
        runner.refuse_if_occupied(conn)


def test_refuse_backup_occupied() -> None:
    conn = FakeConn(responses=[None, "r"])
    with pytest.raises(RuntimeError, match="backup .* already exists"):
        runner.refuse_if_occupied(conn)


def test_build_candidate_failure_cleans_orphan_and_skips_canonical() -> None:
    conn = FakeConn(
        responses=[
            None,
            None,
            False,
            False,  # refuse_if_occupied
            "r",  # MV kind
            None,  # CREATE MV
            None,  # CREATE INDEX
            None,
            None,
            None,  # REVOKEs
            RuntimeError("refresh blew up"),
            None,  # finally: SET statement_timeout = DEFAULT
        ]
    )
    cleaned: list[bool] = []

    def _cleanup(c: Any, *, missing_ok: bool = False) -> dict[str, Any]:
        cleaned.append(missing_ok)
        return {"status": "cleaned"}

    with patch.object(runner, "cleanup_candidate", side_effect=_cleanup):
        with pytest.raises(RuntimeError, match="refresh blew up"):
            runner.build_candidate(conn)

    assert cleaned == [True]
    sql = "\n".join(conn.executed)
    assert runner.CAND in sql
    assert f'ALTER TABLE public."{runner.MV}"' not in sql
    assert "statement_timeout = '15min'" in sql
    assert "statement_timeout = 0" not in sql
    assert "SET statement_timeout = DEFAULT" in sql


def test_fact_snapshot_race_blocks_cutover() -> None:
    snap_a = {
        "n_rows": 10,
        "max_revision": 0,
        "max_price_date": "2026-07-10",
        "grain_hash": 1,
    }
    snap_b = {**snap_a, "n_rows": 11}
    conn = FakeConn()

    with (
        patch.object(runner, "build_candidate"),
        patch.object(runner, "parity_relation", return_value={"ok": True, "name": runner.CAND}),
        patch.object(runner, "fact_snapshot", side_effect=[snap_a, snap_b]),
        patch.object(runner, "final_refresh_candidate") as final_ref,
        patch.object(runner, "cutover") as cut,
    ):
        result = runner.apply_write(conn)

    assert result["status"] == "failed"
    assert result["phase"] == "final_refresh"
    assert "fact snapshot changed" in result["error"]
    final_ref.assert_called_once()
    cut.assert_not_called()


def test_cutover_has_short_lock_timeout_and_no_refresh() -> None:
    snap = {
        "n_rows": 5,
        "max_revision": 0,
        "max_price_date": "2026-07-10",
        "grain_hash": 99,
    }
    # executes: lock, SET lock_timeout, SET statement_timeout,
    # ALTER TABLE, ALTER INDEX, ALTER MV, ALTER INDEX, unlock
    conn = FakeConn(responses=[None] * 8)
    relkinds = iter([None, "m", "r", None])  # bak, cand, mv, post-table-rename

    with (
        patch.object(runner, "fact_snapshot", return_value=snap),
        patch.object(runner, "_relkind", side_effect=lambda _c, _n: next(relkinds)),
        patch.object(runner, "_index_valid", return_value=True),
        patch.object(runner, "_index_exists", return_value=True),
        patch.object(runner, "_revoke_public_roles"),
        patch.object(runner, "parity_relation", return_value={"ok": True, "relkind": "m", "rows": 1}),
    ):
        out = runner.cutover(conn, expected_snap=snap)

    assert out["status"] == "applied"
    joined = "\n".join(conn.executed)
    assert "REFRESH MATERIALIZED VIEW" not in joined
    assert f"lock_timeout = '{runner.CUTOVER_LOCK_TIMEOUT}'" in joined
    assert f'RENAME TO "{runner.BAK}"' in joined
    assert runner.CAND in joined
    assert "statement_timeout = 0" not in joined


def test_cutover_fails_on_raced_snapshot() -> None:
    expected = {
        "n_rows": 1,
        "max_revision": 0,
        "max_price_date": "2026-07-01",
        "grain_hash": 1,
    }
    raced = {**expected, "n_rows": 2}
    # lock + 2 SET LOCAL + unlock in finally
    conn = FakeConn(responses=[None, None, None, None])

    with (
        patch.object(runner, "fact_snapshot", return_value=raced),
        pytest.raises(RuntimeError, match="fact snapshot raced"),
    ):
        runner.cutover(conn, expected_snap=expected)


def test_rollback_restores_table_without_drop_backup() -> None:
    # lock, SET LOCAL, DROP MV, RENAME table, RENAME index, unlock
    conn = FakeConn(responses=[None] * 6)

    with (
        patch.object(runner, "_relkind", side_effect=["r", "m"]),
        patch.object(runner, "_index_exists", return_value=True),
    ):
        result = runner.rollback_cutover(conn)

    assert result["status"] == "rolled_back"
    assert result["backup_dropped"] is False
    joined = "\n".join(conn.executed)
    assert "DROP MATERIALIZED VIEW" in joined
    assert f'RENAME TO "{runner.MV}"' in joined
    assert "DROP TABLE" not in joined


def test_cleanup_candidate_never_touches_backup() -> None:
    conn = FakeConn(responses=["m", None])  # relkind + DROP MV
    with patch.object(runner, "_index_exists", return_value=False):
        result = runner.cleanup_candidate(conn)
    assert result["status"] == "cleaned"
    assert result["backup_untouched"] is True
    joined = "\n".join(conn.executed)
    assert runner.CAND in joined
    assert runner.BAK not in joined
    assert "DROP TABLE" not in joined


def test_apply_write_happy_path_orders_phases() -> None:
    snap = {
        "n_rows": 3,
        "max_revision": 0,
        "max_price_date": "2026-07-10",
        "grain_hash": 7,
    }
    conn = FakeConn()
    order: list[str] = []

    with (
        patch.object(runner, "build_candidate", side_effect=lambda _c: order.append("build")),
        patch.object(
            runner,
            "parity_relation",
            side_effect=lambda _c, name, *, expect_index: (
                order.append(f"parity:{name}") or {"ok": True}
            ),
        ),
        patch.object(runner, "fact_snapshot", side_effect=[snap, snap]),
        patch.object(runner, "final_refresh_candidate", side_effect=lambda _c: order.append("final")),
        patch.object(
            runner,
            "cutover",
            side_effect=lambda _c, expected_snap: (
                order.append("cutover") or {"status": "applied", "parity": {"ok": True}}
            ),
        ),
    ):
        result = runner.apply_write(conn)

    assert result["status"] == "applied"
    assert order == ["build", f"parity:{runner.CAND}", "final", "cutover"]


def test_runner_source_has_no_unbounded_timeout() -> None:
    src = (REPO / "scripts" / "canonicalize_ml_feature_mv.py").read_text(encoding="utf-8")
    assert "statement_timeout = 0" not in src
    assert "statement_timeout = 0" not in src.replace(" ", "")
    assert runner.CAND in src
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY" in src
    assert "--cleanup-candidate" in src
    assert "--rollback" in src
    assert runner.REFRESH_STATEMENT_TIMEOUT.endswith("min")
    assert runner.REFRESH_STATEMENT_TIMEOUT != "0"
