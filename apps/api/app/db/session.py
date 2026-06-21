"""Engine, session factory, and the FastAPI ``get_db`` dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Lazily build the process-wide engine from settings (URL via env)."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().resolved_database_url(), pool_pre_ping=True, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
