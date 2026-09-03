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


# ── currency contract: one instrument, one unit ──────────────────────────────
# A price's unit is declared in TWO places — the profile's `market_instruments`
# entry (which reaches dim_market_instrument, and from there the forecast payload
# and the UI) and the ingestion registry (which reaches fact_price_daily). When the
# two disagree, the same number is rendered in different units on different screens
# and nothing catches it: COMEX_HG was "USc" in the profile while the registry wrote
# USD, so /forecast reported copper at 1/100th of what /prices showed for the very
# same rows.
INGESTION_DIR = REPO_ROOT / "configs" / "ingestion"

#: (commodity_code, instrument_code) -> why the registry unit deliberately differs.
#: Keep this EMPTY unless a proxy series is knowingly stored on another market's
#: instrument; every entry is a rendering bug someone has accepted.
CURRENCY_MISMATCH_WAIVERS = {
    ("CHINESE_GARLIC", "CN_JINXIANG_SPOT"): (
        "garlic_india_proxy: Indian Agmarknet rupee prices stand in for the (unavailable) "
        "Jinxiang CNY spot series. Documented in configs/ingestion/csv_imports.yaml; the "
        "profile already declares an INR IN_NATIONAL_MEDIAN instrument that later imports "
        "use, so this placeholder is a candidate for re-pointing."
    ),
}


def _profile_instrument_currencies() -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for path in PROFILE_FILES:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for inst in data.get("market_instruments") or []:
            out[(data["commodity_code"], inst["instrument_code"])] = inst.get("currency")
    return out


def _registry_entries() -> list[tuple[str, str, str, str]]:
    """(commodity_code, instrument_code, currency, source) for every ingestion entry."""
    entries: list[tuple[str, str, str, str]] = []
    sources = yaml.safe_load((INGESTION_DIR / "sources.yaml").read_text(encoding="utf-8"))
    for inst in (sources.get("prices") or {}).get("instruments") or []:
        entries.append((inst["commodity_code"], inst["instrument_code"], inst.get("currency"), "sources.yaml"))
    imports = yaml.safe_load((INGESTION_DIR / "csv_imports.yaml").read_text(encoding="utf-8"))
    for name, spec in (imports.get("imports") or {}).items():
        entries.append(
            (spec["commodity_code"], spec["instrument_code"], spec.get("currency"), f"csv_imports.yaml:{name}")
        )
    return entries


def test_ingestion_currency_matches_profile_instrument() -> None:
    profile_currencies = _profile_instrument_currencies()
    mismatches = []
    for commodity, instrument, currency, origin in _registry_entries():
        declared = profile_currencies.get((commodity, instrument))
        assert declared is not None, f"{origin}: {commodity}/{instrument} is in no profile"
        if currency is None or currency == declared:
            continue
        if (commodity, instrument) in CURRENCY_MISMATCH_WAIVERS:
            continue
        mismatches.append(f"{origin}: {commodity}/{instrument} registry={currency} profile={declared}")
    assert not mismatches, "ingestion/profile currency disagreement:\n  " + "\n  ".join(mismatches)


def test_currency_waivers_are_still_needed() -> None:
    """A waiver that no longer describes a real mismatch is stale — drop it, so the
    list keeps meaning 'known and accepted', not 'once was true'."""
    profile_currencies = _profile_instrument_currencies()
    live = {
        (c, i)
        for c, i, cur, _ in _registry_entries()
        if cur is not None and profile_currencies.get((c, i)) not in (None, cur)
    }
    stale = set(CURRENCY_MISMATCH_WAIVERS) - live
    assert not stale, f"stale currency waivers, remove them: {sorted(stale)}"
