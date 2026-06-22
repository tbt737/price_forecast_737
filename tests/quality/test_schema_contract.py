"""Phase 2 schema-contract guards — structural checks, no DB server required.

These lock the approved 12-table contract, the point-in-time `release_date`
column on every fact table, the generic (no single-commodity) naming rule, and
the raw SQL mirror invariants (idempotent, non-destructive, complete).

Periodic fact tables use an explicit period range: ``period_start`` + ``period_end``
(+ ``release_date``), guarded by ``CHECK (period_end >= period_start)``. The old
``period_date`` / ``period_type`` grain must not reappear.
"""

from __future__ import annotations

from pathlib import Path

from app.db.base import Base
from app.models import *  # noqa: F401,F403  (register all tables on Base.metadata)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

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


PERIODIC_TABLES = ("fact_logistics_periodic", "fact_supply_demand_periodic")


def test_periodic_facts_use_explicit_period_range() -> None:
    for t in PERIODIC_TABLES:
        cols = {c.name for c in Base.metadata.tables[t].columns}
        assert {"period_start", "period_end", "release_date"} <= cols, f"{t} cols={cols}"
        assert "period_date" not in cols, f"{t} still has period_date"
        assert "period_type" not in cols, f"{t} still has period_type"


def test_periodic_facts_require_data_source_key_not_null() -> None:
    for t in PERIODIC_TABLES:
        col = Base.metadata.tables[t].columns["data_source_key"]
        assert col.nullable is False, f"{t}.data_source_key must be NOT NULL (source lineage)"


def test_periodic_facts_have_period_range_check() -> None:
    sql = SQL_MIRROR.read_text(encoding="utf-8")
    assert "CHECK (period_end >= period_start)" in sql
    # one period-range CHECK per periodic table
    assert sql.count("period_end >= period_start") == len(PERIODIC_TABLES)


def test_sql_mirror_drops_old_period_grain() -> None:
    sql = SQL_MIRROR.read_text(encoding="utf-8")
    assert "period_date" not in sql and "period_type" not in sql


PERIODIC_GRAIN_INDEX = {
    "fact_logistics_periodic": "uq_fact_logistics_grain",
    "fact_supply_demand_periodic": "uq_fact_sd_grain",
}


def _grain_index_ddl(table: str, index_name: str) -> str:
    idx = next(i for i in Base.metadata.tables[table].indexes if i.name == index_name)
    assert idx.unique, f"{index_name} must be UNIQUE"
    return str(CreateIndex(idx).compile(dialect=postgresql.dialect()))


def test_periodic_unique_grain_includes_release_date() -> None:
    for table, index_name in PERIODIC_GRAIN_INDEX.items():
        ddl = _grain_index_ddl(table, index_name)
        assert "release_date" in ddl, f"{table} grain missing release_date: {ddl}"


def test_periodic_unique_grain_includes_data_source_key() -> None:
    for table, index_name in PERIODIC_GRAIN_INDEX.items():
        ddl = _grain_index_ddl(table, index_name)
        assert "data_source_key" in ddl, f"{table} grain missing data_source_key: {ddl}"


def test_periodic_unique_grain_includes_period_range() -> None:
    for table, index_name in PERIODIC_GRAIN_INDEX.items():
        ddl = _grain_index_ddl(table, index_name)
        assert "period_start" in ddl and "period_end" in ddl, f"{table} grain missing period range: {ddl}"


def test_sql_mirror_periodic_grain_lines_include_release_and_source() -> None:
    sql = SQL_MIRROR.read_text(encoding="utf-8")
    for index_name in PERIODIC_GRAIN_INDEX.values():
        line = next(ln for ln in sql.splitlines() if index_name in ln and "UNIQUE INDEX" in ln)
        assert "release_date" in line, line
        assert "data_source_key" in line, line
