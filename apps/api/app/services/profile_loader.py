"""Idempotent loader: commodity YAML profiles -> dimensions + profile registry.

Generic by construction — it walks whatever profiles live in
``configs/commodities/`` and never references a specific commodity. Re-running is
safe: dimensions upsert on their natural ``*_code`` keys, and each profile is
registered with a SHA-256 checksum so an unchanged file is detected and skipped
(no version bump, no duplicate rows).

It loads ONLY reference data (dimensions + registry). Fact tables are populated
by the ETL phase, not here.

Usage:
    python -m app.services.profile_loader                 # load into $DATABASE_URL
    python -m app.services.profile_loader --database-url sqlite:///local.db --create-all
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DEFAULT_PROFILES_DIR
from app.db.base import Base
from app.models import (
    CommodityGroup,
    CommodityProfileRegistry,
    CommodityRegionMap,
    DimCommodity,
    DimDataSource,
    DimMarketInstrument,
    DimRegion,
    RegionRole,
)

# profile region arrays -> dim_region rows + commodity_region_map(role) links
_REGION_ARRAYS: dict[str, RegionRole] = {
    "weather_regions": RegionRole.weather,
    "production_regions": RegionRole.production,
    "consumption_regions": RegionRole.consumption,
    "export_regions": RegionRole.export,
    "import_regions": RegionRole.import_,
}


class LoadSummary(Counter):
    def bump(self, entity: str, action: str) -> None:
        self[f"{entity}:{action}"] += 1

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self.items()))


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _get(entry: Mapping[str, Any] | str, *keys: str) -> Any:
    if isinstance(entry, Mapping):
        for k in keys:
            if k in entry:
                return _norm(entry[k])
    return None


def _upsert(
    session: Session,
    model: type,
    natural_key: dict[str, Any],
    mutable: dict[str, Any],
    summary: LoadSummary,
    entity: str,
    *,
    fill_only_if_empty: Sequence[str] = (),
) -> Any:
    obj = session.execute(select(model).filter_by(**natural_key)).scalar_one_or_none()
    if obj is None:
        obj = model(**natural_key, **mutable)
        session.add(obj)
        session.flush()
        summary.bump(entity, "created")
        return obj

    changed = False
    for key, val in mutable.items():
        if val is None:
            continue
        if key in fill_only_if_empty and getattr(obj, key) not in (None, ""):
            continue
        if getattr(obj, key) != val:
            setattr(obj, key, val)
            changed = True
    summary.bump(entity, "updated" if changed else "unchanged")
    return obj


def load_profile(
    session: Session,
    profile: Mapping[str, Any],
    summary: LoadSummary,
    *,
    source_path: str | None = None,
    raw_text: str | None = None,
) -> DimCommodity:
    """Upsert one profile's dimensions and register it. Returns the DimCommodity."""
    code = _norm(profile["commodity_code"])

    commodity = _upsert(
        session,
        DimCommodity,
        {"commodity_code": code},
        {
            "commodity_name": _norm(profile.get("commodity_name")),
            "commodity_group": CommodityGroup(_norm(profile["commodity_group"])),
            "base_unit": _norm(profile.get("base_unit")),
            "default_currency": _norm(profile.get("default_currency")),
            "notes": _norm(profile.get("notes")),
        },
        summary,
        "dim_commodity",
    )

    # dim_market_instrument (scoped to commodity)
    for entry in profile.get("market_instruments") or []:
        icode = _get(entry, "instrument_code")
        if not icode:
            continue
        _upsert(
            session,
            DimMarketInstrument,
            {"commodity_key": commodity.commodity_key, "instrument_code": icode},
            {
                "exchange": _get(entry, "exchange"),
                "symbol": _get(entry, "symbol"),
                "description": _get(entry, "description"),
                "contract_unit": _get(entry, "contract_unit"),
                "currency": _get(entry, "currency"),
            },
            summary,
            "dim_market_instrument",
        )

    # dim_region (global; deduped) + commodity_region_map (per-commodity role link)
    for array_name, role in _REGION_ARRAYS.items():
        for entry in profile.get(array_name) or []:
            rcode = _get(entry, "region_code")
            if not rcode:
                continue
            label = _get(entry, "name", "region_name") or rcode
            region = _upsert(
                session,
                DimRegion,
                {"region_code": rcode},
                {"region_name": label, "country": _get(entry, "country")},
                summary,
                "dim_region",
                fill_only_if_empty=("region_name", "country"),
            )
            _upsert(
                session,
                CommodityRegionMap,
                {"commodity_key": commodity.commodity_key, "region_key": region.region_key, "role": role},
                {"label": label},
                summary,
                "commodity_region_map",
            )

    # dim_data_source (global)
    for entry in profile.get("data_sources") or []:
        scode = _get(entry, "source_code")
        if not scode:
            continue
        _upsert(
            session,
            DimDataSource,
            {"source_code": scode},
            {
                "name": _get(entry, "name") or scode,
                "url": _get(entry, "url"),
                "access": _get(entry, "access"),
                "license": _get(entry, "license"),
            },
            summary,
            "dim_data_source",
            fill_only_if_empty=("url", "access", "license"),
        )

    _register_profile(session, commodity, profile, summary, source_path=source_path, raw_text=raw_text)
    return commodity


def _register_profile(
    session: Session,
    commodity: DimCommodity,
    profile: Mapping[str, Any],
    summary: LoadSummary,
    *,
    source_path: str | None,
    raw_text: str | None,
) -> None:
    checksum = hashlib.sha256((raw_text or yaml.safe_dump(dict(profile), sort_keys=True)).encode("utf-8")).hexdigest()
    reg = session.execute(
        select(CommodityProfileRegistry).filter_by(commodity_key=commodity.commodity_key)
    ).scalar_one_or_none()

    if reg is None:
        session.add(
            CommodityProfileRegistry(
                commodity_key=commodity.commodity_key,
                commodity_code=commodity.commodity_code,
                source_path=source_path,
                checksum=checksum,
                version=1,
                profile=dict(profile),
            )
        )
        session.flush()
        summary.bump("registry", "created")
    elif reg.checksum == checksum:
        summary.bump("registry", "unchanged")
    else:
        reg.profile = dict(profile)
        reg.checksum = checksum
        reg.source_path = source_path
        reg.version += 1
        summary.bump("registry", "updated")


def load_profiles(session: Session, profiles_dir: Path | str = DEFAULT_PROFILES_DIR) -> LoadSummary:
    """Load every YAML profile in ``profiles_dir``. Caller controls the commit."""
    profiles_dir = Path(profiles_dir)
    summary = LoadSummary()
    files = sorted(profiles_dir.glob("*.yaml")) + sorted(profiles_dir.glob("*.yml"))
    for path in files:
        raw_text = path.read_text(encoding="utf-8")
        profile = yaml.safe_load(raw_text)
        if not profile or "commodity_code" not in profile:
            continue
        load_profile(session, profile, summary, source_path=path.name, raw_text=raw_text)
        summary.bump("profile", "loaded")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load commodity YAML profiles into the database.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL (defaults to env/settings).")
    parser.add_argument("--profiles-dir", default=str(DEFAULT_PROFILES_DIR))
    parser.add_argument("--create-all", action="store_true", help="Create tables from ORM metadata first (dev only).")
    args = parser.parse_args(argv)

    if args.database_url:
        url = args.database_url
    else:
        from app.core.config import get_settings

        url = get_settings().resolved_database_url()

    engine = create_engine(url, future=True)
    if args.create_all:
        Base.metadata.create_all(engine)

    with sessionmaker(bind=engine, future=True)() as session:
        summary = load_profiles(session, args.profiles_dir)
        session.commit()

    print("Profile load complete:")
    for key, count in summary.as_dict().items():
        print(f"  {key:28s} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
