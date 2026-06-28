"""Offline contract test for the forecast-accuracy log migration (Phase ACC-1A).

Reads only ``db/migrations/003_forecast_log.sql`` as text — NO database connection,
NO production write — and asserts the agreed table contract is declared.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "003_forecast_log.sql"

REQUIRED_COLUMNS = [
    "forecast_log_id",
    "forecast_run_id",
    "commodity_code",
    "as_of_date",
    "target_date",
    "horizon_days",
    "model_used",
    "predicted_price",
    "baseline_price",
    "actual_price",
    "actual_available_at",
    "absolute_error",
    "absolute_percentage_error",
    "status",
    "metadata_json",
    "created_at",
    "evaluated_at",
]


def _sql() -> str:
    return MIGRATION.read_text("utf-8")


def _norm(text: str) -> str:
    """Lowercase + collapse whitespace, so multi-token clauses match regardless of layout."""
    return re.sub(r"\s+", " ", text.lower())


def test_migration_file_exists() -> None:
    assert MIGRATION.is_file()


def test_creates_forecast_log_table_idempotently() -> None:
    assert "create table if not exists fact_forecast_log" in _norm(_sql())


def test_has_all_required_columns() -> None:
    sql = _norm(_sql())
    for col in REQUIRED_COLUMNS:
        assert col in sql, f"missing column: {col}"


def test_value_constraints_present() -> None:
    sql = _norm(_sql())
    assert "check (predicted_price > 0)" in sql
    assert "check (horizon_days in (30, 90))" in sql
    assert "check (target_date > as_of_date)" in sql


def test_status_values_constrained() -> None:
    sql = _norm(_sql())
    assert "status in ('pending', 'evaluated', 'expired', 'invalid')" in sql
    for value in ("'pending'", "'evaluated'", "'expired'", "'invalid'"):
        assert value in sql


def test_unique_grain_declared() -> None:
    sql = _norm(_sql())
    assert "unique (commodity_code, as_of_date, target_date, horizon_days, model_used)" in sql


def test_required_indexes_present() -> None:
    sql = _norm(_sql())
    assert "ix_forecast_log_pending" in sql
    assert "where status = 'pending'" in sql  # partial index for pending-evaluation lookup
    assert "ix_forecast_log_commodity_asof" in sql
    assert "ix_forecast_log_target_date" in sql


def test_additive_and_no_destructive_statements() -> None:
    sql = _norm(_sql())
    assert "drop table" not in sql
    assert "drop column" not in sql
    assert "delete from" not in sql
    assert "truncate" not in sql


def test_contract_check_requires_no_db() -> None:
    # The whole suite here is a pure file read — proves the contract can be validated
    # offline with no DATABASE_URL / network / production write.
    assert len(_sql()) > 0
