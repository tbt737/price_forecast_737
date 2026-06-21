"""Pytest fixtures: in-memory SQLite DB, a seeded session, and a TestClient.

Tests run on SQLite (no PostgreSQL needed) because the ORM schema is portable.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import *  # noqa: F401,F403  (register all tables on Base.metadata)
from app.services.profile_loader import load_profiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    sess = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture()
def seeded_session(session: Session) -> Session:
    """Session with all real commodity profiles loaded into the dimensions/registry."""
    load_profiles(session)
    session.commit()
    return session


@pytest.fixture()
def client(seeded_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: seeded_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
