"""Request/response schemas for forecast endpoints.

Request is strict (extra forbid, safe commodity code, horizon allowlist).
Response models document the shape returned by ``ml.forecast.forecast_commodity``
so OpenAPI and the web ``types.ts`` mirror stay aligned.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown fields ⇒ 422

    # snake_case/uppercase identifiers only; bounded length; blocks '.', '/', '%', …
    commodity_code: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}$")
    # allowlist — the engine forecasts 30 and 90 trading days; anything else ⇒ 422
    horizon_days: Literal[30, 90]
    # the production forecaster already supports this flag safely (Phase 8B)
    enable_ou: bool = True


class ForecastPointOut(BaseModel):
    date: str
    value: float
    lower: float
    upper: float


class BacktestSummaryOut(BaseModel):
    folds: int
    mape_pct: float | None = None
    naive_mape_pct: float | None = None
    beats_naive: bool
    candidates: dict[str, float] | None = None
    ou_considered: bool | None = None


class HorizonForecastOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    model_used: str | None = None
    # Optional so OpenAPI still documents the production shape while test/mocks
    # may return a partial horizon object.
    points: list[ForecastPointOut] | None = None
    backtest: BacktestSummaryOut | None = None


class ForecastOut(BaseModel):
    """GET /commodities/{code}/forecast and POST /forecast response body."""

    model_config = ConfigDict(extra="allow")  # tolerate optional engine fields

    available: bool
    commodity_code: str
    reason: str | None = None
    instrument_code: str | None = None
    currency: str | None = None
    model: str | None = None
    history_points: int | None = None
    last_date: str | None = None
    last_price: float | None = None
    horizons: dict[str, HorizonForecastOut] | None = None
    # POST /forecast may attach a flat points list for the requested horizon
    points: list[dict[str, Any]] | None = None
