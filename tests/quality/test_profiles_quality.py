"""Data-quality gate: every commodity YAML profile is well-formed.

Pure file validation (no DB) — guards the configuration contract that the whole
platform is keyed on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = REPO_ROOT / "configs" / "commodities"

REQUIRED_KEYS = {
    "commodity_code",
    "commodity_name",
    "commodity_group",
    "base_unit",
    "default_currency",
    "market_instruments",
    "weather_regions",
    "production_regions",
    "consumption_regions",
    "export_regions",
    "import_regions",
    "physical_drivers",
    "macro_drivers",
    "logistics_drivers",
    "event_risk_drivers",
    "data_sources",
    "models",
    "notes",
}
VALID_GROUPS = {"agriculture", "energy", "metal", "logistics", "equity"}

PROFILE_FILES = sorted(PROFILES_DIR.glob("*.yaml"))


def test_sixteen_profiles_present() -> None:
    assert len(PROFILE_FILES) == 52  # 22 commodities + 30 VN30 equities (Vietnam domestic)


@pytest.mark.parametrize("path", PROFILE_FILES, ids=lambda p: p.stem)
def test_profile_is_valid(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} is not a mapping"
    missing = REQUIRED_KEYS - data.keys()
    assert not missing, f"{path.name} missing keys: {missing}"
    assert data["commodity_group"] in VALID_GROUPS, data["commodity_group"]
    # no required array is empty (sentinels are allowed but must be non-empty)
    for key in REQUIRED_KEYS:
        if isinstance(data[key], list):
            assert data[key], f"{path.name}: array '{key}' is empty"
