"""Contract tests for ML feature refresh gate + canonicalize migration plan."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from scripts.refresh_ml_features import (
    MV_NAME,
    UNIQUE_INDEX,
    classify_mv_relation,
)
from scripts.refresh_ml_features import (
    main as refresh_main,
)

REPO = Path(__file__).resolve().parents[2]
PREAMBLE = REPO / "db" / "migrations" / "005_mv_ml_canonicalize_preamble.sql"
ROLLBACK = REPO / "db" / "migrations" / "005_mv_ml_canonicalize_rollback.sql"
RUNBOOK = REPO / "docs" / "ml" / "feature_view_refresh_runbook.md"


def test_refresh_dry_run_exits_zero() -> None:
    assert refresh_main([]) == 0


def test_classify_missing() -> None:
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    status, detail = classify_mv_relation(session)
    assert status == "missing"
    assert MV_NAME in detail


def test_classify_wrong_kind_table() -> None:
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = "r"
    status, detail = classify_mv_relation(session)
    assert status == "wrong_kind"
    assert "CONTRACT_VIOLATION" in detail


def test_classify_matview_ready() -> None:
    session = MagicMock()
    # first execute → relkind; second → unique exists
    rel = MagicMock()
    rel.scalar_one_or_none.return_value = "m"
    uniq = MagicMock()
    uniq.scalar.return_value = True
    session.execute.side_effect = [rel, uniq]
    status, detail = classify_mv_relation(session)
    assert status == "matview_ready"
    assert UNIQUE_INDEX.split("_")[0] in detail or "ready" in detail


def test_classify_matview_no_unique() -> None:
    session = MagicMock()
    rel = MagicMock()
    rel.scalar_one_or_none.return_value = "m"
    uniq = MagicMock()
    uniq.scalar.return_value = False
    session.execute.side_effect = [rel, uniq]
    status, detail = classify_mv_relation(session)
    assert status == "matview_no_unique"
    assert "CONTRACT_VIOLATION" in detail


def test_offline_builder_constants_decoupled() -> None:
    from ml.build_pandas_mv import OFFLINE_TABLE, PRODUCTION_MV

    assert OFFLINE_TABLE != PRODUCTION_MV
    assert OFFLINE_TABLE.startswith("offline_")
    assert PRODUCTION_MV == "mv_ml_daily_features_wide"


def test_canonicalize_runner_uses_two_phase_operator_boundary() -> None:
    runner = (REPO / "scripts" / "canonicalize_ml_feature_mv.py").read_text(encoding="utf-8")
    assert "pg_advisory_lock" in runner
    assert "--prepare-candidate" in runner
    assert "--cutover" in runner
    assert "--rollback" in runner
    assert "--cleanup-candidate" in runner
    assert "mv_ml_daily_features_wide_cand" in runner
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY" in runner
    assert "statement_timeout = 0" not in runner
    assert "lock_timeout" in runner
    assert "fact_snapshot" in runner
    assert "fact_event_risk" in runner
    assert "DEFAULT_REFRESH_TIMEOUT_MIN = 30" in runner
    assert "--write is removed" in runner or "write is removed" in runner

    preamble = PREAMBLE.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")

    for needle in (
        "prepare-candidate",
        "cutover",
        "candidate",
        "RENAME TO",
        "mv_ml_daily_features_wide_table_bak",
        "WITH NO DATA",
        "lock_timeout",
        "REVOKE",
        "30",
    ):
        assert needle.lower() in (preamble + runbook + runner).lower(), needle

    assert "DROP MATERIALIZED VIEW" in rollback
    assert "mv_ml_daily_features_wide_table_bak" in rollback
    assert "parity" in runbook.lower()
    assert "canonicalize_ml_feature_mv.py" in runbook
    assert "offline_ml_daily_features_wide_pandas" in runbook
    assert "operator" in runbook.lower()
    assert "six" in runbook.lower() or "fact_event_risk" in runbook
    assert "pg_advisory_lock" in runner


def test_generated_mv_sql_is_with_no_data() -> None:
    sql = (REPO / "db" / "views" / "generated" / "010_mv_ml_daily_features_wide.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ml_daily_features_wide" in sql
    assert "WITH NO DATA" in sql
