"""FastAPI application entrypoint.

Run locally (from apps/api): ``uvicorn app.main:app --reload``
Phase 2 exposes health/readiness + read-only commodity & profile endpoints only.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.routers import commodities, health


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Commodity Quant Forecasting Platform API",
        version=__version__,
        summary="Generic, configuration-driven commodity forecasting platform (Phase 2: data layer).",
    )
    app.include_router(health.router)
    app.include_router(commodities.router)
    return app


app = create_app()
