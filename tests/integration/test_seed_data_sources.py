"""Integration: dim_data_source seed is idempotent, complete, and non-destructive."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.models import DimDataSource  # noqa: F401  (register tables)
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.seeds.seed_data_sources import SEED_SOURCE_CODES, seed_data_sources


@pytest.fixture()
def session() -> Iterator[Session]:
    engine: Engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, future=True)()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _codes(session: Session) -> set[str]:
    return set(session.execute(select(DimDataSource.source_code)).scalars())


def test_required_source_codes_present_after_seed(session: Session) -> None:
    seed_data_sources(session)
    session.commit()
    assert {"manual", "internal", "unknown", "seed_profile"} <= _codes(session)
    assert set(SEED_SOURCE_CODES) <= _codes(session)


def test_seed_is_idempotent(session: Session) -> None:
    first = seed_data_sources(session)
    session.commit()
    count_after_first = session.scalar(select(func.count()).select_from(DimDataSource))

    second = seed_data_sources(session)
    session.commit()
    count_after_second = session.scalar(select(func.count()).select_from(DimDataSource))

    assert first["created"] == len(SEED_SOURCE_CODES)
    assert second["created"] == 0  # nothing new on the second run
    assert count_after_first == count_after_second


def test_seed_does_not_delete_existing_sources(session: Session) -> None:
    session.add(DimDataSource(source_code="ICE", name="ICE / Barchart", access="subscription"))
    session.flush()
    seed_data_sources(session)
    session.commit()
    codes = _codes(session)
    assert "ICE" in codes  # pre-existing source preserved
    assert {"manual", "internal", "unknown", "seed_profile"} <= codes
