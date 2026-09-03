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


def test_exit_code_reconcile_error_is_failure() -> None:
    # A reconcile report with any fail-closed per-instrument error must NOT exit 0
    # (the cron step is continue-on-error, but the red step must still be visible).
    assert _exit_code({"mode": "write", "instruments": [{"status": "error"}], "ok": False}) == 1
    assert _exit_code({"mode": "dry_run", "instruments": [{"status": "empty"}], "ok": True}) == 0


def _count_committed_sources(factory) -> int:
    from sqlalchemy import text

    with factory() as s:  # a FRESH session: only committed rows are visible
        return s.execute(text("select count(*) from dim_data_source")).scalar()


def test_dry_run_commits_nothing_but_write_still_seeds(monkeypatch) -> None:
    """`python -m etl.ingest` is documented as writing nothing, and .claude/loop-profile.md
    sanctions it as the read-only production smoke while the local .env points at the LIVE
    database. Seeding dim_data_source COMMITS, so it must sit behind the write-mode guard.
    Offline: in-memory SQLite, and `run` is stubbed so no connector touches the network."""
    import sys

    import app.db.session as session_module
    import app.models  # noqa: F401  (registers the metadata)
    from app.db.base import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from etl import ingest as ingest_module

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(session_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        ingest_module, "run", lambda *a, **k: {"mode": "dry_run", "instruments": [], "ok": True}
    )

    assert _count_committed_sources(factory) == 0
    monkeypatch.setattr(sys, "argv", ["etl.ingest"])
    ingest_module.main()
    assert _count_committed_sources(factory) == 0, "the documented dry-run committed rows"

    monkeypatch.setattr(sys, "argv", ["etl.ingest", "--write"])
    ingest_module.main()
    assert _count_committed_sources(factory) > 0, "--write must still seed the reference rows"
