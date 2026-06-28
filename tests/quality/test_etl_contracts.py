"""ETL contract + validation guards (pure — no DB, no network)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from app.db.base import Base
from app.models import *  # noqa: F401,F403  (register fact tables on metadata)

from etl.contracts import APPROVED_FACT_TABLES, FACT_FAMILIES, FactFamily, NormalizedRecord
from etl.validation import ErrorCode, Severity, validate_record

REPO_ROOT = Path(__file__).resolve().parents[2]
ETL_DIR = REPO_ROOT / "etl"

SCHEMA_FACT_TABLES = {t for t in Base.metadata.tables if t.startswith("fact_")}
SINGLE_COMMODITY_TOKENS = ("robusta", "gold", "copper", "rice", "corn", "wheat", "cocoa", "sugar", "soybean")
NETWORK_TOKENS = ("import requests", "import httpx", "import urllib", "import socket", "urlopen", "yfinance")
# Real-source connectors are the DELIBERATE network boundary (automated ingestion);
# the core pipeline stays offline. Only these adapters may touch the network.
NETWORK_EXEMPT = {
    ETL_DIR / "ingest.py",
    ETL_DIR / "sources" / "market" / "yahoo.py",
    ETL_DIR / "sources" / "market" / "vn_domestic.py",
    ETL_DIR / "sources" / "weather" / "nasa_power.py",
    ETL_DIR / "sources" / "macro" / "yahoo_fx.py",
    ETL_DIR / "sources" / "events" / "noaa_oni.py",
    ETL_DIR / "sources" / "supply_demand" / "usda_psd.py",
    ETL_DIR / "sources" / "supply_demand" / "usda_psd_bulk.py",
}


def _valid_sd() -> NormalizedRecord:
    return NormalizedRecord(
        family=FactFamily.supply_demand_periodic,
        data_source_code="manual",
        release_date=date(2025, 2, 10),
        commodity_code="ROBUSTA",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        metric_code="ending_stocks",
        value=100,
    )


def test_every_family_maps_to_an_approved_fact_table() -> None:
    for fam, spec in FACT_FAMILIES.items():
        assert spec.family is fam
        assert spec.target_table in APPROVED_FACT_TABLES


def test_approved_targets_match_schema_fact_tables() -> None:
    assert APPROVED_FACT_TABLES == SCHEMA_FACT_TABLES


def test_all_six_families_present() -> None:
    assert set(FACT_FAMILIES) == set(FactFamily)
    assert len(FACT_FAMILIES) == 6


def test_missing_source_is_error() -> None:
    rec = NormalizedRecord(**{**_valid_sd().__dict__, "data_source_code": None})
    res = validate_record(rec)
    assert not res.ok and ErrorCode.MISSING_SOURCE in res.error_codes


def test_missing_release_date_is_error() -> None:
    rec = NormalizedRecord(**{**_valid_sd().__dict__, "release_date": None})
    res = validate_record(rec)
    assert not res.ok and ErrorCode.MISSING_RELEASE_DATE in res.error_codes


def test_periodic_requires_period_bounds() -> None:
    rec = NormalizedRecord(**{**_valid_sd().__dict__, "period_start": None, "period_end": None})
    res = validate_record(rec)
    assert not res.ok and ErrorCode.INVALID_PERIOD_RANGE in res.error_codes


def test_periodic_rejects_reversed_range() -> None:
    rec = NormalizedRecord(**{**_valid_sd().__dict__, "period_start": date(2025, 2, 1), "period_end": date(2025, 1, 1)})
    res = validate_record(rec)
    assert not res.ok and ErrorCode.INVALID_PERIOD_RANGE in res.error_codes


def test_lookahead_release_before_period_end() -> None:
    rec = NormalizedRecord(**{**_valid_sd().__dict__, "release_date": date(2025, 1, 15)})  # before period_end
    res = validate_record(rec)
    assert not res.ok and ErrorCode.LOOKAHEAD_UNSAFE in res.error_codes


def test_daily_requires_observation_date() -> None:
    rec = NormalizedRecord(
        family=FactFamily.macro_daily, data_source_code="manual", release_date=date(2025, 1, 10),
        indicator_code="dxy", observation_date=None,
    )
    res = validate_record(rec)
    assert ErrorCode.LOOKAHEAD_UNSAFE in res.error_codes


def test_weather_requires_region() -> None:
    rec = NormalizedRecord(
        family=FactFamily.weather_daily, data_source_code="manual", release_date=date(2025, 1, 10),
        commodity_code="ROBUSTA", observation_date=date(2025, 1, 10), metric_code="rainfall_mm",
    )
    res = validate_record(rec)
    assert ErrorCode.MISSING_REGION in res.error_codes


def test_supply_demand_requires_commodity() -> None:
    rec = NormalizedRecord(**{**_valid_sd().__dict__, "commodity_code": None})
    res = validate_record(rec)
    assert ErrorCode.MISSING_COMMODITY in res.error_codes


def test_metric_required_for_macro() -> None:
    rec = NormalizedRecord(
        family=FactFamily.macro_daily, data_source_code="manual", release_date=date(2025, 1, 10),
        observation_date=date(2025, 1, 10), indicator_code=None,
    )
    res = validate_record(rec)
    assert ErrorCode.MISSING_METRIC in res.error_codes


def test_price_missing_instrument_is_warning_not_error() -> None:
    rec = NormalizedRecord(
        family=FactFamily.price_daily, data_source_code="manual", release_date=date(2025, 1, 10),
        commodity_code="ROBUSTA", observation_date=date(2025, 1, 10), instrument_code=None,
    )
    res = validate_record(rec)
    assert res.ok  # warning only
    assert any(i.code is ErrorCode.MISSING_INSTRUMENT and i.severity is Severity.warning for i in res.warnings)


def test_valid_record_passes() -> None:
    res = validate_record(_valid_sd())
    assert res.ok and not res.errors


def test_etl_code_is_generic_no_single_commodity() -> None:
    # whole-word match so "rice" does not falsely hit "price"
    for path in ETL_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in SINGLE_COMMODITY_TOKENS:
            assert not re.search(rf"\b{token}\b", text), f"{path} hardcodes commodity '{token}'"


def test_core_pipeline_needs_no_network_or_credentials() -> None:
    exempt = {p.resolve() for p in NETWORK_EXEMPT}
    for path in ETL_DIR.rglob("*.py"):
        if path.resolve() in exempt:
            continue  # connector adapters are the sanctioned network boundary
        text = path.read_text(encoding="utf-8")
        for token in NETWORK_TOKENS:
            assert token not in text, f"{path} references network/external dependency '{token}'"
