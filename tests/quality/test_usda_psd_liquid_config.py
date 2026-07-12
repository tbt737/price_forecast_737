"""USDA PSD liquid supply_demand config: catalog alignment, aliases, duplicates."""

from __future__ import annotations

from copy import deepcopy

import pytest
import yaml

from etl.ingestion.config import (
    CONFIG_PATH,
    SupplyDemandMetricDetail,
    SupplyDemandSpec,
    load_ingestion_config,
    parse_supply_demand_metrics,
)
from etl.ingestion.validate_psd import (
    CATALOG_PATH,
    STANDARD_ROLES,
    load_psd_attribute_catalog,
    validate_supply_demand_config,
)
from etl.sources.supply_demand.usda_psd_bulk import UsdaPsdBulkSource
from ml.models.mechanistic_fourier import has_supply_drivers, resolve_supply_column


LIQUID_FULL_TRIAD = ("CORN", "WHEAT", "SOYBEAN", "RICE")
LIQUID_PARTIAL = ("SUGAR",)


def test_psd_catalog_covers_requested_liquids() -> None:
    cat = load_psd_attribute_catalog()
    for code in (*LIQUID_FULL_TRIAD, *LIQUID_PARTIAL, "COCOA"):
        assert code in cat
    assert cat["COCOA"]["usda_commodity_id"] is None
    assert cat["SUGAR"]["roles"]["planted_area"] is None
    for code in LIQUID_FULL_TRIAD:
        for role in STANDARD_ROLES:
            role_spec = cat[code]["roles"][role]
            assert role_spec is not None
            assert int(role_spec["attribute_id"]) > 0
            assert role_spec["unit"]
            assert role_spec["usda_attribute"]


def test_sources_yaml_liquid_series_match_catalog() -> None:
    cfg = load_ingestion_config()
    by_code = {s.commodity_code: s for s in cfg.supply_demand}
    assert "COCOA" not in by_code
    cat = load_psd_attribute_catalog()

    for code in LIQUID_FULL_TRIAD:
        spec = by_code[code]
        assert set(spec.metrics) == set(STANDARD_ROLES)
        for role in STANDARD_ROLES:
            expected = cat[code]["roles"][role]
            assert spec.metrics[role] == int(expected["attribute_id"])
            detail = next(d for d in spec.metric_details if d.metric_code == role)
            assert detail.unit == expected["unit"]
            assert detail.usda_attribute == expected["usda_attribute"]

    sugar = by_code["SUGAR"]
    assert set(sugar.metrics) == {"import_volume", "inventory"}
    assert "planted_area" not in sugar.metrics
    assert sugar.usda_commodity_id == cat["SUGAR"]["usda_commodity_id"]


def test_robusta_legacy_int_metrics_still_load() -> None:
    cfg = load_ingestion_config()
    robusta = next(s for s in cfg.supply_demand if s.commodity_code == "ROBUSTA")
    assert robusta.metrics == {
        "production_estimate": 28,
        "exportable_surplus": 88,
        "certified_stocks": 178,
    }


def test_mechanistic_aliases_resolve_configured_roles() -> None:
    cfg = load_ingestion_config()
    for code in LIQUID_FULL_TRIAD:
        cols = list(next(s for s in cfg.supply_demand if s.commodity_code == code).metrics)
        assert has_supply_drivers(cols)
        assert resolve_supply_column(cols, "planted_area") == "planted_area"
        assert resolve_supply_column(cols, "import_volume") == "import_volume"
        assert resolve_supply_column(cols, "inventory") == "inventory"
    sugar_cols = list(next(s for s in cfg.supply_demand if s.commodity_code == "SUGAR").metrics)
    assert not has_supply_drivers(sugar_cols)


def test_validate_rejects_duplicate_commodity_and_attribute() -> None:
    base = SupplyDemandSpec(
        "CORN",
        "0440000",
        "USDA_FAS",
        0,
        {"planted_area": 4, "import_volume": 57, "inventory": 176},
        (
            SupplyDemandMetricDetail("planted_area", 4, "(1000 HA)", "Area Harvested"),
            SupplyDemandMetricDetail("import_volume", 57, "(1000 MT)", "Imports"),
            SupplyDemandMetricDetail("inventory", 176, "(1000 MT)", "Ending Stocks"),
        ),
    )
    dup_commodity = SupplyDemandSpec(
        "CORN",
        "0410000",
        "USDA_FAS",
        0,
        {"planted_area": 4, "import_volume": 57, "inventory": 176},
        base.metric_details,
    )
    errors = validate_supply_demand_config([base, dup_commodity])
    assert any("duplicate commodity_code" in e for e in errors)

    dup_attr = SupplyDemandSpec(
        "WHEAT",
        "0410000",
        "USDA_FAS",
        0,
        {"planted_area": 4, "import_volume": 4, "inventory": 176},
        (
            SupplyDemandMetricDetail("planted_area", 4, "(1000 HA)", "Area Harvested"),
            SupplyDemandMetricDetail("import_volume", 4, "(1000 MT)", "Imports"),
            SupplyDemandMetricDetail("inventory", 176, "(1000 MT)", "Ending Stocks"),
        ),
    )
    errors = validate_supply_demand_config([base, dup_attr])
    assert any("attribute_id 4 mapped to both" in e for e in errors)


def test_validate_rejects_invented_sugar_planted_area_and_cocoa() -> None:
    bad_sugar = SupplyDemandSpec(
        "SUGAR",
        "0612000",
        "USDA_FAS",
        0,
        {"planted_area": 4, "import_volume": 57, "inventory": 176},
        (
            SupplyDemandMetricDetail("planted_area", 4, "(1000 HA)", "Area Harvested"),
            SupplyDemandMetricDetail("import_volume", 57, "(1000 MT)", "Imports"),
            SupplyDemandMetricDetail("inventory", 176, "(1000 MT)", "Ending Stocks"),
        ),
    )
    errors = validate_supply_demand_config([bad_sugar])
    assert any("planted_area" in e and "not published" in e for e in errors)

    cocoa = SupplyDemandSpec("COCOA", "9999999", "USDA_FAS", 0, {"inventory": 176}, ())
    errors = validate_supply_demand_config([cocoa])
    assert any("unavailable" in e or "must not appear" in e for e in errors)


def test_validate_rejects_wrong_unit() -> None:
    bad = SupplyDemandSpec(
        "CORN",
        "0440000",
        "USDA_FAS",
        0,
        {"planted_area": 4, "import_volume": 57, "inventory": 176},
        (
            SupplyDemandMetricDetail("planted_area", 4, "(MT)", "Area Harvested"),
            SupplyDemandMetricDetail("import_volume", 57, "(1000 MT)", "Imports"),
            SupplyDemandMetricDetail("inventory", 176, "(1000 MT)", "Ending Stocks"),
        ),
    )
    errors = validate_supply_demand_config([bad])
    assert any("unit" in e and "planted_area" in e for e in errors)


def test_parse_metrics_legacy_and_rich() -> None:
    ids, details = parse_supply_demand_metrics({"production_estimate": 28})
    assert ids == {"production_estimate": 28}
    assert details[0].unit is None

    ids, details = parse_supply_demand_metrics(
        {"planted_area": {"attribute_id": 4, "unit": "(1000 HA)", "usda_attribute": "Area Harvested"}}
    )
    assert ids == {"planted_area": 4}
    assert details[0].usda_attribute == "Area Harvested"

    with pytest.raises(ValueError, match="attribute_id"):
        parse_supply_demand_metrics({"planted_area": {"unit": "(1000 HA)"}})


def test_load_rejects_mutated_sources_with_duplicate_series(tmp_path) -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    mutated = deepcopy(raw)
    series = mutated["supply_demand"]["series"]
    series.append(deepcopy(series[1]))  # duplicate CORN block
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate commodity_code"):
        load_ingestion_config(path)


def test_bulk_connector_dry_run_liquid_fixture_no_db() -> None:
    """Dry-run collect() for liquid roles using an in-memory CSV fixture — no DB write."""
    csv = """Commodity_Code,Commodity_Description,Country_Code,Country_Name,Market_Year,Calendar_Year,Month,Attribute_ID,Attribute_Description,Unit_ID,Unit_Description,Value
0440000,Corn,US,United States,2024,2024,10,4,Area Harvested,8,(1000 HA),100.0
0440000,Corn,US,United States,2024,2024,10,57,Imports,8,(1000 MT),10.0
0440000,Corn,US,United States,2024,2024,10,176,Ending Stocks,8,(1000 MT),20.0
0410000,Wheat,US,United States,2024,2024,10,4,Area Harvested,8,(1000 HA),50.0
0410000,Wheat,US,United States,2024,2024,10,57,Imports,8,(1000 MT),5.0
0410000,Wheat,US,United States,2024,2024,10,176,Ending Stocks,8,(1000 MT),8.0
2222000,"Oilseed, Soybean",US,United States,2024,2024,10,4,Area Harvested,8,(1000 HA),40.0
2222000,"Oilseed, Soybean",US,United States,2024,2024,10,57,Imports,8,(1000 MT),3.0
2222000,"Oilseed, Soybean",US,United States,2024,2024,10,176,Ending Stocks,8,(1000 MT),7.0
0612000,"Sugar, Centrifugal",BR,Brazil,2024,2024,10,57,Imports,8,(1000 MT),1.0
0612000,"Sugar, Centrifugal",BR,Brazil,2024,2024,10,176,Ending Stocks,8,(1000 MT),2.0
0422110,"Rice, Milled",VN,Vietnam,2024,2024,10,4,Area Harvested,8,(1000 HA),9.0
0422110,"Rice, Milled",VN,Vietnam,2024,2024,10,57,Imports,8,(1000 MT),0.5
0422110,"Rice, Milled",VN,Vietnam,2024,2024,10,176,Ending Stocks,8,(1000 MT),1.5
9999999,Other,XX,Somewhere,2024,2024,10,4,Area Harvested,8,(1000 HA),1.0
"""
    cfg = load_ingestion_config()
    liquids = [
        s
        for s in cfg.supply_demand
        if s.commodity_code in (*LIQUID_FULL_TRIAD, *LIQUID_PARTIAL)
    ]
    records = list(UsdaPsdBulkSource(liquids, fetch=lambda: csv).collect())
    by_pair = {(r.commodity_code, r.metric_code) for r in records}
    expected = {
        ("CORN", "planted_area"),
        ("CORN", "import_volume"),
        ("CORN", "inventory"),
        ("WHEAT", "planted_area"),
        ("WHEAT", "import_volume"),
        ("WHEAT", "inventory"),
        ("SOYBEAN", "planted_area"),
        ("SOYBEAN", "import_volume"),
        ("SOYBEAN", "inventory"),
        ("SUGAR", "import_volume"),
        ("SUGAR", "inventory"),
        ("RICE", "planted_area"),
        ("RICE", "import_volume"),
        ("RICE", "inventory"),
    }
    assert by_pair == expected
    assert all(r.unit in {"(1000 HA)", "(1000 MT)"} for r in records)


def test_catalog_file_exists_next_to_sources() -> None:
    assert CATALOG_PATH.is_file()
    assert CONFIG_PATH.is_file()
