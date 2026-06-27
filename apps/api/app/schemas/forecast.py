"""Request schema for the guarded forecast-execution endpoint (Phase 7C).

Strict by construction: unknown fields are rejected, the commodity code is
constrained to a safe identifier charset (no path-traversal characters), and the
horizon is an allowlist — so no arbitrary value reaches the ML boundary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown fields ⇒ 422

    # snake_case/uppercase identifiers only; bounded length; blocks '.', '/', '%', …
    commodity_code: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}$")
    # allowlist — the engine forecasts 30 and 90 trading days; anything else ⇒ 422
    horizon_days: Literal[30, 90]
    # the production forecaster already supports this flag safely (Phase 8B)
    enable_ou: bool = True
