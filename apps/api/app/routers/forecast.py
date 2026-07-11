"""Guarded forecast-execution endpoint (Phase 7C).

POST /forecast runs the existing production forecaster for a validated
commodity/horizon through the read-only ``forecast_commodity`` boundary. Mounted
only behind ``ENABLE_ML_FORECAST_API`` (OFF by default — see ``app.main``).

Safety: strict request validation (see ``ForecastRequest``); the ML call is
wrapped so an unexpected failure returns a generic 503 with no traceback, module
path, DB URL, or secret. Read-only — ``forecast_commodity`` never writes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.forecast import ForecastOut, ForecastRequest

router = APIRouter(tags=["forecast"])


@router.post("/forecast", response_model=ForecastOut)
def run_forecast(req: ForecastRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Execute a 30/90-day price forecast for one commodity. 404 when the commodity
    is unknown or has too little history; 503 on an unexpected engine failure."""
    code = req.commodity_code.upper()

    # Imported lazily so module import stays free of any ML/DB side effects.
    from ml.forecast import forecast_commodity

    try:
        result = forecast_commodity(db, code, horizons=(req.horizon_days,), enable_ou=req.enable_ou)
    except Exception:  # noqa: BLE001 — fail closed: never surface internals to the client
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Forecast service temporarily unavailable"
        ) from None

    if not result.get("available", False):
        reason = str(result.get("reason", "not available"))
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Forecast not available for '{code}': {reason}")
    return result
