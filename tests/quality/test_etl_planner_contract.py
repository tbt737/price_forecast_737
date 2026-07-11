"""Phase 3B contract guards: grain coverage, error codes, generic + offline."""

from __future__ import annotations

import re
from pathlib import Path

from etl.conflicts import GRAIN_FIELDS, TARGET_MODELS
from etl.contracts import APPROVED_FACT_TABLES, FactFamily
from etl.validation import ErrorCode

REPO_ROOT = Path(__file__).resolve().parents[2]
ETL_DIR = REPO_ROOT / "etl"
PERIODIC_FAMILIES = (FactFamily.logistics_periodic, FactFamily.supply_demand_periodic)
SINGLE_COMMODITY_TOKENS = ("robusta", "gold", "copper", "rice", "corn", "wheat", "cocoa", "sugar", "soybean")
NETWORK_TOKENS = ("import requests", "import httpx", "import urllib", "import socket", "urlopen", "yfinance")
# Real-source connectors are the DELIBERATE network boundary (automated ingestion);
# the core pipeline stays offline. Only these adapters may touch the network.
NETWORK_EXEMPT = {
    ETL_DIR / "ingest.py",
    ETL_DIR / "sources" / "market" / "yahoo.py",
    ETL_DIR / "sources" / "market" / "vn_domestic.py",
    ETL_DIR / "sources" / "market" / "vn_stocks.py",
    ETL_DIR / "sources" / "weather" / "nasa_power.py",
    ETL_DIR / "sources" / "macro" / "yahoo_fx.py",
    ETL_DIR / "sources" / "events" / "noaa_oni.py",
    ETL_DIR / "sources" / "supply_demand" / "usda_psd.py",
    ETL_DIR / "sources" / "supply_demand" / "usda_psd_bulk.py",
}


def test_unknown_error_codes_exist() -> None:
    for name in ("UNKNOWN_COMMODITY", "UNKNOWN_REGION", "UNKNOWN_INSTRUMENT", "UNKNOWN_SOURCE"):
        assert hasattr(ErrorCode, name)


def test_target_models_cover_all_families() -> None:
    assert set(TARGET_MODELS) == set(FactFamily)
    assert {m.__tablename__ for m in TARGET_MODELS.values()} == APPROVED_FACT_TABLES


def test_grain_fields_defined_for_all_families() -> None:
    assert set(GRAIN_FIELDS) == set(FactFamily)


def test_periodic_grain_includes_source_and_release_and_period() -> None:
    required = {"data_source_key", "release_date", "period_start", "period_end", "revision"}
    for fam in PERIODIC_FAMILIES:
        assert required <= set(GRAIN_FIELDS[fam]), f"{fam}: {GRAIN_FIELDS[fam]}"


def test_grain_columns_exist_on_target_models() -> None:
    for fam, cols in GRAIN_FIELDS.items():
        model_cols = {c.name for c in TARGET_MODELS[fam].__table__.columns}
        assert set(cols) <= model_cols, f"{fam}: {set(cols) - model_cols}"


def test_phase3b_code_is_generic_no_single_commodity() -> None:
    for path in ETL_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in SINGLE_COMMODITY_TOKENS:
            assert not re.search(rf"\b{token}\b", text), f"{path} hardcodes commodity '{token}'"


def test_core_pipeline_needs_no_network() -> None:
    exempt = {p.resolve() for p in NETWORK_EXEMPT}
    for path in ETL_DIR.rglob("*.py"):
        if path.resolve() in exempt:
            continue  # connector adapters are the sanctioned network boundary
        text = path.read_text(encoding="utf-8")
        for token in NETWORK_TOKENS:
            assert token not in text, f"{path} references network '{token}'"
