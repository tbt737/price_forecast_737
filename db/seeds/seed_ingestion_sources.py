"""Idempotent seed for ingestion ``dim_data_source`` rows (yahoo, NASA_POWER).

Connector-originated facts carry these source codes; they must exist before any
write. Additive only, never deletes, no credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from app.models import DimDataSource  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

INGESTION_SOURCES: dict[str, tuple[str, str]] = {
    "yahoo": ("Yahoo Finance (daily futures prices via yfinance)", "public"),
    "NASA_POWER": ("NASA POWER agroclimatology (daily weather)", "public"),
    "csv_import": ("Imported from a local CSV dataset (e.g. Kaggle/Agmarknet)", "public"),
    "NOAA": ("NOAA Climate Prediction Center", "public"),
    "USDA_FAS": ("USDA Foreign Agricultural Service (PSD)", "public"),
    "PNJ": ("PNJ public gold-price endpoint (Vietnam domestic)", "public"),
    "PHU_QUY": ("Phú Quý Group silver-price partial (Vietnam domestic)", "public"),
    "VNAPPMOB": ("VNAppMob Gold API v2 (historical SJC, Vietnam domestic)", "public"),
    "GIATIEU": ("giatieu.com public daily domestic pepper-price page (Vietnam domestic)", "public"),
}


def seed_ingestion_sources(session: Session) -> dict[str, int]:
    """Insert any missing ingestion sources. Idempotent; never deletes. Caller commits."""
    created = 0
    for code, (name, access) in INGESTION_SOURCES.items():
        exists = session.execute(select(DimDataSource).filter_by(source_code=code)).scalar_one_or_none()
        if exists is None:
            session.add(DimDataSource(source_code=code, name=name, access=access))
            created += 1
    session.flush()
    return {"created": created, "ingestion_codes": len(INGESTION_SOURCES)}


def main() -> int:
    from app.core.config import get_settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(get_settings().resolved_database_url(), future=True)
    with sessionmaker(bind=engine, future=True)() as session:
        summary = seed_ingestion_sources(session)
        session.commit()
    print(f"Seeded ingestion sources: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
