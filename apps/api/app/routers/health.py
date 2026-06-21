"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.db.session import get_db
from app.schemas.commodity import HealthOut, ReadyOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Liveness: the process is up. Does not touch the database."""
    return HealthOut(status="ok", version=__version__)


@router.get("/ready", response_model=ReadyOut)
def ready(response: Response, db: Session = Depends(get_db)) -> ReadyOut:
    """Readiness: verify the database is reachable (SELECT 1)."""
    try:
        db.execute(text("SELECT 1"))
        return ReadyOut(status="ready", database="up")
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyOut(status="not_ready", database="down")
