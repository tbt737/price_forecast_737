"""Phase 2 schema-contract guards — structural checks, no DB server required.

These lock the approved 12-table contract, the point-in-time `release_date`
column on every fact table, the generic (no single-commodity) naming rule, and
the raw SQL mirror invariants (idempotent, non-destructive, complete).

NOTE: column-level grain of the *periodic* fact tables (period_date vs
period_start/period_end) is intentionally NOT asserted here — that is an open
owner decision (see the overnight report), so this guard checks only invariants
that hold regardless of that decision.
"""

from __future__ import annotations

from pathlib import Path

from app.db.base import Base
from app.models import *  # noqa: F401,F403  (register all tables on Base.metadata)

REPO_ROOT = Path(__file__).resolve().parents[2]
SQL_MIRROR = REPO_ROOT / "db" / "migrations" / "001_core_schema.sql"
MIGRATION = REPO_ROOT / "apps" / "api" / "app" / "migrations" / "versions" / "0001_core_star_schema.py"

APPROVED_TABLES = {
    "dim_commodity",
    "dim_market_instrument",
    "dim_region",
    "commodity_region_map",
    "dim_data_source",
    "fact_price_daily",
    "fact_weather_daily",
    "fact_macro_daily",
    "fact_logistics_periodic",
    "fact_supply_demand_periodic",
    "fact_event_risk",
    "commodity_profile_registry",
}
FACT_TABLES = {t for t in APPROVED_TABLES if t.startswith("fact_")}
# representative single-commodity tokens that must never appear as a name segment
# (matched against underscore-delimited segments, so e.g. "rice" does not falsely
# match "price" in fact_price_daily)
SINGLE_COMMODITY_TOKENS = (
    "robusta", "gold", "copper", "rice", "corn", "wheat",
    "cocoa", "sugar", "soybean", "peanut", "garlic", "onion", "chili", "crude",
)


def test_metadata_is_exactly_the_12_approved_tables() -> None:
    assert set(Base.metadata.tables) == APPROVED_TABLES


def test_all_fact_tables_have_release_date() -> None:
    for t in FACT_TABLES:
        cols = {c.name for c in Base.metadata.tables[t].columns}
        assert "release_date" in cols, f"{t} missing release_date"


def test_no_single_commodity_table_names() -> None:
    segments = {seg for name in Base.metadata.tables for seg in name.split("_")}
    for token in SINGLE_COMMODITY_TOKENS:
        assert token not in segments, f"table name hardcodes commodity '{token}'"


def test_fact_event_risk_in_metadata_and_migration() -> None:
    assert "fact_event_risk" in Base.metadata.tables
    assert "op.create_table('fact_event_risk'" in MIGRATION.read_text(encoding="utf-8")


def test_migration_table_set_matches_approved() -> None:
    import re

    text = MIGRATION.read_text(encoding="utf-8")
    tables = set(re.findall(r"op\.create_table\('([a-z_]+)'", text))
    assert tables == APPROVED_TABLES


def test_sql_mirror_uses_create_table_if_not_exists_for_all_tables() -> None:
    sql = SQL_MIRROR.read_text(encoding="utf-8")
    for t in APPROVED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {t} " in sql, f"{t} missing IF NOT EXISTS create"


def test_sql_mirror_has_no_executable_drop() -> None:
    for line in SQL_MIRROR.read_text(encoding="utf-8").splitlines():
        code = line.split("--", 1)[0]  # ignore comments
        assert "DROP" not in code.upper(), f"executable DROP found: {line!r}"


def test_sql_mirror_has_release_date_index_per_fact_table() -> None:
    sql = SQL_MIRROR.read_text(encoding="utf-8")
    for t in FACT_TABLES:
        assert f"ix_{t}_release_date" in sql, f"{t} missing release_date index in SQL mirror"
