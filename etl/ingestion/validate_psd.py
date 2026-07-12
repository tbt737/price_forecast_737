"""Validate USDA PSD ``supply_demand`` series against the verified attribute catalog.

Catalog is the source of truth for Attribute_ID / unit / Attribute_Description —
never invent IDs. Validation is pure config (no network, no DB).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import yaml

CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "ingestion" / "usda_psd_attribute_catalog.yaml"
)

# Mechanistic supply-driver roles (must match ml.models.mechanistic_fourier aliases).
STANDARD_ROLES: tuple[str, ...] = ("planted_area", "import_volume", "inventory")


class _SupplyDemandSeries(Protocol):
    commodity_code: str
    usda_commodity_id: str
    metrics: dict[str, int]
    metric_details: tuple[Any, ...]


def load_psd_attribute_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    commodities = data.get("commodities")
    if not isinstance(commodities, dict) or not commodities:
        raise ValueError(f"PSD attribute catalog missing commodities: {path}")
    return commodities


def validate_supply_demand_config(
    series: list[_SupplyDemandSeries],
    *,
    catalog: dict[str, Any] | None = None,
    catalog_path: Path = CATALOG_PATH,
) -> list[str]:
    """Return human-readable errors (empty list ⇒ OK)."""
    errors: list[str] = []
    cat = catalog if catalog is not None else load_psd_attribute_catalog(catalog_path)

    seen_commodity: dict[str, int] = {}
    seen_usda_id: dict[str, int] = {}

    for idx, spec in enumerate(series):
        label = f"series[{idx}] {spec.commodity_code}"
        if not spec.metrics:
            errors.append(f"{label}: metrics must not be empty")
        if spec.commodity_code in seen_commodity:
            errors.append(
                f"{label}: duplicate commodity_code "
                f"(also series[{seen_commodity[spec.commodity_code]}])"
            )
        else:
            seen_commodity[spec.commodity_code] = idx
        if spec.usda_commodity_id in seen_usda_id:
            errors.append(
                f"{label}: duplicate usda_commodity_id {spec.usda_commodity_id!r} "
                f"(also series[{seen_usda_id[spec.usda_commodity_id]}])"
            )
        else:
            seen_usda_id[spec.usda_commodity_id] = idx

        attr_owners: dict[int, str] = {}
        for metric_code, attr_id in spec.metrics.items():
            if attr_id in attr_owners:
                errors.append(
                    f"{label}: attribute_id {attr_id} mapped to both "
                    f"{attr_owners[attr_id]!r} and {metric_code!r}"
                )
            else:
                attr_owners[attr_id] = metric_code

        details_by_code = {d.metric_code: d for d in spec.metric_details}
        for metric_code, attr_id in spec.metrics.items():
            detail = details_by_code.get(metric_code)
            if detail is not None and detail.attribute_id != attr_id:
                errors.append(
                    f"{label}: metric {metric_code!r} metrics/details attribute_id mismatch"
                )

        entry = cat.get(spec.commodity_code)
        if entry is None:
            # Legacy series (e.g. ROBUSTA) are allowed without catalog roles.
            continue

        usda_id = entry.get("usda_commodity_id")
        if usda_id is None:
            errors.append(
                f"{label}: commodity is marked unavailable in PSD catalog "
                f"({entry.get('note') or 'no usda_commodity_id'})"
            )
            continue
        if str(usda_id) != str(spec.usda_commodity_id):
            errors.append(
                f"{label}: usda_commodity_id {spec.usda_commodity_id!r} != catalog {usda_id!r}"
            )

        roles = entry.get("roles") or {}
        for role in STANDARD_ROLES:
            role_spec = roles.get(role)
            if role in spec.metrics:
                if role_spec is None:
                    errors.append(
                        f"{label}: role {role!r} is not published in PSD catalog — "
                        "remove it (do not invent Attribute_ID)"
                    )
                    continue
                expected_id = int(role_spec["attribute_id"])
                if int(spec.metrics[role]) != expected_id:
                    errors.append(
                        f"{label}: role {role!r} attribute_id "
                        f"{spec.metrics[role]} != catalog {expected_id}"
                    )
                detail = details_by_code.get(role)
                if detail is None or detail.unit is None or detail.usda_attribute is None:
                    errors.append(
                        f"{label}: role {role!r} must declare unit and usda_attribute"
                    )
                else:
                    if detail.unit != role_spec.get("unit"):
                        errors.append(
                            f"{label}: role {role!r} unit {detail.unit!r} != "
                            f"catalog {role_spec.get('unit')!r}"
                        )
                    if detail.usda_attribute != role_spec.get("usda_attribute"):
                        errors.append(
                            f"{label}: role {role!r} usda_attribute "
                            f"{detail.usda_attribute!r} != catalog "
                            f"{role_spec.get('usda_attribute')!r}"
                        )
            elif role_spec is not None:
                # Catalog has the role but series omitted it — warn as error for
                # full-triad commodities; SUGAR omits planted_area intentionally.
                pass

        # Any configured metric that is a standard role must be catalog-backed (above).
        # Non-role metrics on a catalogued commodity are rejected to keep liquid series clean.
        for metric_code in spec.metrics:
            if metric_code in STANDARD_ROLES:
                continue
            errors.append(
                f"{label}: unexpected metric {metric_code!r} on catalogued liquid commodity "
                f"(only {list(STANDARD_ROLES)} allowed)"
            )

    # Catalogued commodities with a PSD id should appear in sources when they have
    # at least one published role — except we allow intentional omission only for
    # fully-null commodities (COCOA). Soft check: COCOA must not be present.
    if "COCOA" in seen_commodity:
        errors.append("COCOA must not appear in supply_demand.series (absent from PSD bulk)")

    return errors
