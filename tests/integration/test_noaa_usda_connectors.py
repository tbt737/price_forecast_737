"""Integration: NOAA ONI and USDA PSD connectors (no network)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from etl.ingestion.config import EventRiskSpec, SupplyDemandSpec, load_ingestion_config
from etl.provenance import gate_record
from etl.sources.events.noaa_oni import NoaaOniSource, _parse_oni_lines
from etl.sources.supply_demand.usda_psd import UsdaPsdSource
from etl.sources.supply_demand.usda_psd_bulk import UsdaPsdBulkSource

NOAA_SAMPLE = """ YEAR   SEAS   TOTAL   ANOM
 2024   DJF    24.72   0.85
 2024   JFM    25.10   1.12
 2024   NDJ    24.50   0.50
"""

USDA_CSV_SAMPLE = """Commodity_Code,Country_Code,Market_Year,Month,Attribute_ID,Value,Unit_Description
0711100,VM,2024,10,28,1500.0,1000 MT
0711100,VM,2024,10,88,500.0,1000 MT
0711100,VM,2024,10,178,200.0,1000 MT
0711100,BR,2024,10,28,7777.0,1000 MT
9999999,VM,2024,10,28,999.0,1000 MT
"""


def test_ingestion_config_includes_noaa_and_usda_sources() -> None:
    cfg = load_ingestion_config()
    assert {"NOAA", "USDA_FAS"} <= cfg.source_codes
    assert cfg.events and cfg.supply_demand
    oni = next(m for m in cfg.events if m.metric_code == "el_nino_la_nina")
    assert oni.source_code == "NOAA"
    robusta = next(s for s in cfg.supply_demand if s.commodity_code == "ROBUSTA")
    assert robusta.usda_commodity_id == "0711100"
    assert robusta.country_code == "VM" and robusta.region_code == "VN"


def test_parse_oni_lines_maps_season_end_dates() -> None:
    rows = _parse_oni_lines(NOAA_SAMPLE.splitlines())
    by_date = {r["date"]: r["value"] for r in rows}
    assert by_date[date(2024, 2, 1)] == 0.85
    assert by_date[date(2024, 3, 1)] == 1.12
    assert by_date[date(2025, 1, 1)] == 0.50  # NDJ 2024 ends Jan 2025


def test_noaa_connector_builds_records_with_provenance() -> None:
    spec = EventRiskSpec("el_nino_la_nina", "climate", "manual", release_lag_days=10)

    def fetch() -> list[dict]:
        return _parse_oni_lines(NOAA_SAMPLE.splitlines())

    records = list(NoaaOniSource([spec], fetch=fetch).collect())
    assert len(records) == 3
    r = records[0]
    assert r.metric_code == "el_nino_la_nina"
    assert r.data_source_code == "manual"
    assert r.observation_date == date(2024, 2, 1)
    assert r.release_date == date(2024, 2, 1) + timedelta(days=31 + 10)
    assert r.source_record_id == "manual:noaa_oni_ascii:2024-02-01"
    assert gate_record(r) == []


def test_noaa_connector_ignores_unconfigured_metrics() -> None:
    spec = EventRiskSpec("other_metric", "climate", "manual", release_lag_days=10)
    records = list(NoaaOniSource([spec], fetch=lambda: _parse_oni_lines(NOAA_SAMPLE.splitlines())).collect())
    assert records == []


def test_noaa_connector_fails_soft_on_empty_or_parse_error() -> None:
    """A flaky/empty NOAA response must NOT raise (it would kill the whole ingest)."""
    spec = EventRiskSpec("el_nino_la_nina", "climate", "manual", release_lag_days=10)

    def boom() -> list[dict]:
        raise RuntimeError("NOAA ONI response contained no parseable rows")

    assert list(NoaaOniSource([spec], fetch=boom).collect()) == []  # fail soft → empty


def test_noaa_connector_fails_soft_on_network_error() -> None:
    spec = EventRiskSpec("el_nino_la_nina", "climate", "manual", release_lag_days=10)

    def neterr() -> list[dict]:
        raise OSError("connection refused")  # URLError/socket errors subclass OSError

    assert list(NoaaOniSource([spec], fetch=neterr).collect()) == []


def test_daily_prices_path_excludes_noaa() -> None:
    """The critical daily prices path must not include the flaky NOAA connector."""
    from etl.ingest import build_connectors

    cfg = load_ingestion_config()
    names = {
        type(c).__name__
        for c in build_connectors(cfg, which="prices", period="5d", weather_days=10, today=date(2026, 6, 26))
    }
    assert "YahooPriceSource" in names
    assert "NoaaOniSource" not in names


def test_usda_bulk_connector_filters_one_country_and_attaches_provenance() -> None:
    spec = SupplyDemandSpec(
        "ROBUSTA",
        "0711100",
        "manual",
        release_lag_days=0,
        metrics={"production_estimate": 28, "exportable_surplus": 88, "certified_stocks": 178},
        country_code="VM",
        region_code="VN",
    )
    records = list(UsdaPsdBulkSource([spec], fetch=lambda: USDA_CSV_SAMPLE).collect())
    metrics = {r.metric_code for r in records}
    assert metrics == {"production_estimate", "exportable_surplus", "certified_stocks"}
    assert all(r.commodity_code == "ROBUSTA" for r in records)
    assert all(r.region_code == "VN" for r in records)  # BR row (7777.0) must be excluded
    assert all(r.value != 7777.0 for r in records)
    assert all(r.data_source_code == "manual" for r in records)
    assert all(gate_record(r) == [] for r in records)
    ids = [r.source_record_id for r in records]
    assert len(ids) == len(set(ids))  # provenance collision = 0
    prod = next(r for r in records if r.metric_code == "production_estimate")
    assert prod.period_start == date(2024, 10, 1)
    assert prod.value == 1500.0
    assert prod.source_record_id == "manual:0711100:2024-10-01_28_VM"


def test_usda_bulk_connector_fails_closed_on_empty_csv() -> None:
    spec = SupplyDemandSpec(
        "ROBUSTA", "0711100", "manual", 0, {"production_estimate": 28}, country_code="VM"
    )
    with pytest.raises(RuntimeError, match="empty"):
        list(UsdaPsdBulkSource([spec], fetch=lambda: "").collect())


def test_usda_bulk_connector_fails_closed_on_no_matching_rows() -> None:
    spec = SupplyDemandSpec(
        "ROBUSTA", "0711100", "manual", 0, {"production_estimate": 28}, country_code="VM"
    )
    csv = "Commodity_Code,Country_Code,Market_Year,Month,Attribute_ID,Value\n9999999,VM,2024,10,28,1.0\n"
    with pytest.raises(RuntimeError, match="no rows matching"):
        list(UsdaPsdBulkSource([spec], fetch=lambda: csv).collect())


def test_usda_bulk_connector_fails_closed_on_missing_country() -> None:
    """Configured country absent from the CSV must raise, not silently emit nothing."""
    spec = SupplyDemandSpec(
        "ROBUSTA",
        "0711100",
        "manual",
        0,
        {"production_estimate": 28, "exportable_surplus": 88},
        country_code="ID",  # sample has VM/BR only
    )
    both = SupplyDemandSpec(
        "ROBUSTA_VM", "0711100", "manual", 0, {"production_estimate": 28}, country_code="VM"
    )
    with pytest.raises(RuntimeError, match=r"NO rows.*ROBUSTA.*@ID"):
        list(UsdaPsdBulkSource([spec, both], fetch=lambda: USDA_CSV_SAMPLE).collect())


def test_usda_bulk_connector_fails_closed_on_unconfigured_country() -> None:
    spec = SupplyDemandSpec("ROBUSTA", "0711100", "manual", 0, {"production_estimate": 28})
    with pytest.raises(ValueError, match="country_code is required"):
        list(UsdaPsdBulkSource([spec], fetch=lambda: USDA_CSV_SAMPLE).collect())


def test_usda_bulk_connector_fails_closed_on_duplicate_grain() -> None:
    dup_csv = """Commodity_Code,Country_Code,Market_Year,Month,Attribute_ID,Value,Unit_Description
0711100,VM,2024,10,28,1.0,1000 MT
0711100,VM,2024,10,28,2.0,1000 MT
"""
    spec = SupplyDemandSpec(
        "ROBUSTA", "0711100", "manual", 0, {"production_estimate": 28}, country_code="VM"
    )
    with pytest.raises(RuntimeError, match="duplicate grain"):
        list(UsdaPsdBulkSource([spec], fetch=lambda: dup_csv).collect())


def test_usda_api_connector_builds_records_with_mock_fetch() -> None:
    spec = SupplyDemandSpec("ROBUSTA", "0711100", "manual", 0, {"production_estimate": 28})

    def fetch(_commodity_id: str) -> list[dict]:
        return [
            {
                "attribute_id": 28,
                "market_year": 2024,
                "start_date": date(2024, 10, 1),
                "value": 1500.0,
            }
        ]

    records = list(UsdaPsdSource([spec], fetch=fetch).collect())
    assert len(records) == 1
    r = records[0]
    assert r.metric_code == "production_estimate"
    assert r.value == 1500.0
    assert gate_record(r) == []