"""SEC-2 internal-API-key gate on the compute-heavy GET /forecast endpoint.

Unit tests of the dependency + integration tests via TestClient. The cached Settings
instance's ``internal_api_key`` is monkeypatched per test (auto-reverted).
"""

from __future__ import annotations

import pytest
from app.core import config
from app.core.security import require_internal_key
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _set_key(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(config.get_settings(), "internal_api_key", value)


# ── unit: the dependency ─────────────────────────────────────────────────────
def test_dependency_503_when_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # FAIL-CLOSED: a protected endpoint with no server key is a misconfiguration → 503,
    # never silently public.
    _set_key(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        require_internal_key(x_internal_key=None)
    assert exc.value.status_code == 503


def test_dependency_503_ignores_any_header_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        require_internal_key(x_internal_key="anything")  # a client key can't unlock a misconfigured server
    assert exc.value.status_code == 503


def test_dependency_401_when_set_but_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, "secret-123")
    with pytest.raises(HTTPException) as exc:
        require_internal_key(x_internal_key=None)
    assert exc.value.status_code == 401


def test_dependency_401_on_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, "secret-123")
    with pytest.raises(HTTPException) as exc:
        require_internal_key(x_internal_key="wrong")
    assert exc.value.status_code == 401


def test_dependency_passes_on_correct_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, "secret-123")
    assert require_internal_key(x_internal_key="secret-123") is None


# ── integration: the /forecast route ─────────────────────────────────────────
def test_forecast_503_when_key_unset(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Misconfigured server ⇒ 503 and compute never runs (the dependency short-circuits
    # before the route body, so a 503 proves forecast_commodity was not invoked).
    _set_key(monkeypatch, None)
    assert client.get("/commodities/GOLD/forecast").status_code == 503


def test_forecast_401_without_header_when_set(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, "secret-123")
    assert client.get("/commodities/GOLD/forecast").status_code == 401


def test_forecast_401_on_wrong_header(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, "secret-123")
    r = client.get("/commodities/GOLD/forecast", headers={"X-Internal-Key": "wrong"})
    assert r.status_code == 401


def test_forecast_passes_with_correct_header(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch, "secret-123")
    r = client.get("/commodities/GOLD/forecast", headers={"X-Internal-Key": "secret-123"})
    assert r.status_code != 401  # gate cleared (forecast may be 200 available:false with no seed data)


def test_public_endpoints_never_gated(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Even with a key configured, health/ready/stats stay public — only /forecast is gated.
    _set_key(monkeypatch, "secret-123")
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/stats").status_code == 200
