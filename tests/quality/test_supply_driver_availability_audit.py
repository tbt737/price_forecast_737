"""Unit tests for SUPPLY_DRIVER_AVAILABILITY_AUDIT helpers (no DB)."""

from __future__ import annotations

from scripts.supply_driver_availability_audit import (
    CommodityAudit,
    approx_walk_forward_folds,
    format_report,
    metric_codes_for_role,
)


def test_approx_walk_forward_folds_too_short() -> None:
    assert approx_walk_forward_folds(100) == 0
    assert approx_walk_forward_folds(282) == 0  # last_cut=252 == min_train → 0


def test_approx_walk_forward_folds_enough_history() -> None:
    # n=400, horizon=30 → last_cut=370 > 252 → up to 5 folds
    assert approx_walk_forward_folds(400) == 5


def test_metric_codes_include_inventory_aliases() -> None:
    codes = metric_codes_for_role("inventory")
    assert "inventory" in codes
    assert "cold_storage_inventory" in codes


def test_format_report_mentions_gate() -> None:
    audit = CommodityAudit(
        commodity_code="DEHYDRATED_GARLIC",
        commodity_key=1,
        price_n_positive=10,
        price_date_min=None,
        price_date_max=None,
        price_approx_wf_folds_h30=0,
        drivers=[],
        roles_with_data=[],
        roles_missing=["planted_area", "import_volume", "inventory"],
        mechanistic_ready=False,
        mv_columns_present=[],
        notes=["missing supply roles: planted_area, import_volume, inventory"],
    )
    text = format_report([audit])
    assert "SUPPLY_DRIVER_AVAILABILITY_AUDIT" in text
    assert "mechanistic_ready: False" in text
    assert "do NOT add drivers to canonical MV" in text
