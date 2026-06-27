"""FastAPI application entrypoint.

Run locally (from apps/api): ``uvicorn app.main:app --reload``
Exposes health/readiness + read-only commodity/profile endpoints, plus a
self-contained static dashboard at ``/`` (no Node/npm toolchain).
"""

from __future__ import annotations

import sys
from pathlib import Path

# The /forecast endpoint lazily imports the repo-root ``ml`` package. Ensure the
# repo root is importable no matter how uvicorn is launched (from apps/api or root),
# otherwise the forecast endpoint fails with ModuleNotFoundError: No module named 'ml'.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from app import __version__  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.routers import commodities, forecast, health, models  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Commodity Quant Forecasting Platform API",
        version=__version__,
        summary="Generic, configuration-driven commodity forecasting platform (Phase 2: data layer).",
    )
    app.include_router(health.router)
    app.include_router(commodities.router)
    # Phase 7B: experimental ML model-registry API — mounted only behind the
    # ENABLE_ML_MODELS_API flag (OFF by default), so it is inert in production
    # until explicitly enabled.
    if get_settings().enable_ml_models_api:
        app.include_router(models.router)
    # Phase 7C: guarded forecast-execution endpoint — likewise OFF by default.
    if get_settings().enable_ml_forecast_api:
        app.include_router(forecast.router)

    @app.get("/", include_in_schema=False, response_model=None)
    def dashboard() -> FileResponse | JSONResponse:
        """Serve the lightweight read-only dashboard (falls back to JSON if absent)."""
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"status": "ok", "dashboard": "not built", "docs": "/docs"})

    return app


app = create_app()
