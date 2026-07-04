"""ETL-VN-3: the ingest CLI exit code must reflect a silent write failure, and the
backfill path must accept a history-days window. Pure — no DB/network."""

from __future__ import annotations

import inspect

from etl.backfill import backfill
from etl.ingest import _exit_code


def test_exit_code_write_rollback_is_failure() -> None:
    # The bug this guards: a write batch that rolled back (committed:false) must NOT exit 0.
    assert _exit_code({"mode": "write", "write": {"mode": "write", "committed": False, "inserted": 0}}) == 1


def test_exit_code_write_committed_is_ok() -> None:
    assert _exit_code({"write": {"mode": "write", "committed": True, "inserted": 3}}) == 0


def test_exit_code_dry_run_is_ok() -> None:
    assert _exit_code({"write": {"mode": "dry_run", "committed": None}}) == 0


def test_exit_code_backfill_result_is_ok() -> None:
    # Backfill returns no 'write' key; a re-run with 0 new rows (ON CONFLICT) is success.
    assert _exit_code({"collected": 3, "inserted": {"price_daily": 3}, "inserted_total": 3}) == 0
    assert _exit_code({"collected": 3, "inserted": {}, "inserted_total": 0}) == 0


def test_backfill_accepts_history_days() -> None:
    # vn_history top-up (--history-days 7) must thread through the backfill path.
    assert "history_days" in inspect.signature(backfill).parameters
