"""Idempotent seed for baseline ``dim_data_source`` rows.

Guarantees the source-lineage rows that ETL needs before inserting any fact
(periodic facts require a non-null ``data_source_key``). Safe by construction:
additive only (never deletes), no external network, no credentials/secrets.

Run standalone:  python db/seeds/seed_data_sources.py     (reads DATABASE_URL)
Or import ``seed_data_sources(session)`` from tests / app code.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the FastAPI app package importable when run as a standalone script.
_API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from app.models import DimDataSource  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

# Baseline sources. Codes are stable identifiers; never delete these.
SEED_SOURCES: dict[str, str] = {
    "manual": "Manually entered / hand-curated data",
    "internal": "Internally derived or computed series",
    "unknown": "Source not recorded (placeholder lineage)",
    "seed_profile": "Seeded from commodity YAML profile metadata",
}
SEED_SOURCE_CODES: tuple[str, ...] = tuple(SEED_SOURCES)


def seed_data_sources(session: Session) -> dict[str, int]:
    """Insert any missing baseline sources. Idempotent; never deletes. Caller commits."""
    created = 0
    for code, name in SEED_SOURCES.items():
        exists = session.execute(select(DimDataSource).filter_by(source_code=code)).scalar_one_or_none()
        if exists is None:
            session.add(DimDataSource(source_code=code, name=name, access="internal"))
            created += 1
    session.flush()
    return {"created": created, "seed_codes": len(SEED_SOURCES)}


def main() -> int:
    from app.core.config import get_settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(get_settings().resolved_database_url(), future=True)
    with sessionmaker(bind=engine, future=True)() as session:
        summary = seed_data_sources(session)
        session.commit()
    print(f"Seeded dim_data_source: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
