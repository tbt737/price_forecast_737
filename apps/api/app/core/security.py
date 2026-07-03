"""Internal-API-key gate for compute-heavy endpoints (SEC-2).

The always-on GET /forecast runs a multi-second walk-forward pool on an
``--allow-unauthenticated`` Cloud Run service. This dependency requires an
``X-Internal-Key`` header that only ``cqp-web`` injects server-side (never exposed to
the browser bundle).

**FAIL-CLOSED.** A protected endpoint with a missing server key is a *misconfiguration*,
not an open door: if ``INTERNAL_API_KEY`` is unset the endpoint returns 503 (never runs
compute) rather than silently going public — so a lost/rolled-back Cloud Run env can't
re-expose it. When the key IS set, missing/wrong headers get a 401 (constant-time
compare). The correct rollout is to provision the key on both services first, then
deploy (SEC-2B). The key is never logged; neither expected nor provided value is returned.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import get_settings

_INTERNAL_KEY_HEADER = "X-Internal-Key"


def require_internal_key(
    x_internal_key: str | None = Header(default=None, alias=_INTERNAL_KEY_HEADER),
) -> None:
    """FastAPI dependency (runs BEFORE the route body, so compute never starts on a
    rejected request). 503 when the server key is unconfigured; 401 on missing/mismatch."""
    key = get_settings().internal_api_key
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API key is not configured",
        )
    if not x_internal_key or not hmac.compare_digest(x_internal_key, key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
