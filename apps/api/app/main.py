"""FastAPI application entrypoint.

Run locally (from apps/api): ``uvicorn app.main:app --reload``
Exposes health/readiness + read-only commodity/profile endpoints, plus a
self-contained static dashboard at ``/`` (no Node/npm toolchain).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app import __version__
from app.routers import commodities, health

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Commodity Quant Forecasting Platform API",
        version=__version__,
        summary="Generic, configuration-driven commodity forecasting platform (Phase 2: data layer).",
    )
    app.include_router(health.router)
    app.include_router(commodities.router)

    @app.get("/", include_in_schema=False, response_model=None)
    def dashboard() -> FileResponse | JSONResponse:
        """Serve the lightweight read-only dashboard (falls back to JSON if absent)."""
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"status": "ok", "dashboard": "not built", "docs": "/docs"})

    return app


app = create_app()
