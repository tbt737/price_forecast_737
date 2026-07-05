"""ML-FIX-1: API guards.

- GET /commodities/{code}/prices: ``days`` is bounded, so an absurd value returns 422
  instead of a 500 from a ``date`` underflow.
- GET /commodities/{code}/forecast: an unexpected engine failure fails CLOSED — a clean
  503 with no traceback / module path / DB URL leaked.
"""

from __future__ import annotations

import pytest
from app.core import config
from app.routers.commodities import _FORECAST_CACHE
from fastapi.testclient import TestClient


def test_prices_days_overflow_is_422_not_500(client: TestClient) -> None:
    # days=999999999 ⇒ `date.today() - timedelta(days=...)` underflows below date.min → 500.
    # Bounded input returns a clean 422 instead.
    assert client.get("/commodities/GOLD/prices?days=999999999").status_code == 422


def test_prices_days_below_and_above_bounds_are_422(client: TestClient) -> None:
    assert client.get("/commodities/GOLD/prices?days=0").status_code == 422
    assert client.get("/commodities/GOLD/prices?days=-5").status_code == 422
    assert client.get("/commodities/GOLD/prices?days=20001").status_code == 422  # just over the cap


def test_prices_days_at_upper_bound_is_ok(client: TestClient) -> None:
    # Inclusive max: 20000 is valid (returns all history for the seeded commodity, possibly empty).
    assert client.get("/commodities/GOLD/prices?days=20000").status_code == 200


def test_forecast_fails_closed_503_on_engine_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # An unexpected exception inside forecast_commodity must become a clean 503 — never a 500
    # with a stack trace, module path, or DB URL in the body.
    monkeypatch.setattr(config.get_settings(), "internal_api_key", "k")  # clear SEC-2 gate
    _FORECAST_CACHE.clear()  # ensure the route actually computes (not a warm cache hit)

    import ml.forecast as mlf

    def _boom(*_a: object, **_k: object) -> dict:
        # Stands in for any sensitive internal (conn string, module path, etc.) an engine
        # exception might carry; the fail-closed guard must echo NONE of it to the client.
        raise RuntimeError("INTERNAL_LEAK_MARKER at /srv/secret/path")

    monkeypatch.setattr(mlf, "forecast_commodity", _boom)

    r = client.get("/commodities/GOLD/forecast", headers={"X-Internal-Key": "k"})
    assert r.status_code == 503
    body = r.json()
    assert body["detail"] == "Forecast service temporarily unavailable"
    # No internals leaked into the client response.
    blob = str(body)
    assert "INTERNAL_LEAK_MARKER" not in blob
    assert "/srv/secret" not in blob
    assert "Traceback" not in blob


def test_forecast_failure_is_not_cached(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # A failed compute must not poison the cache — a later healthy call must be free to succeed.
    monkeypatch.setattr(config.get_settings(), "internal_api_key", "k")
    _FORECAST_CACHE.clear()

    import ml.forecast as mlf

    monkeypatch.setattr(mlf, "forecast_commodity", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert client.get("/commodities/GOLD/forecast", headers={"X-Internal-Key": "k"}).status_code == 503
    assert "GOLD" not in _FORECAST_CACHE  # nothing cached on failure
