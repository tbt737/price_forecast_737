"""Phase 7C — the guarded forecast-execution endpoint (POST /forecast) is gated by
``ENABLE_ML_FORECAST_API`` (default OFF), validates all inputs strictly, and maps
engine failures to safe HTTP errors with no internal leakage. ML core is mocked —
no DB, no real forecast.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def clean_settings_cache():
    import app.core.config as cfg

    cfg._settings = None
    yield
    cfg._settings = None


class _FakeSession:
    """Stand-in DB session: records writes, refuses real queries (forecast is mocked)."""

    def __init__(self) -> None:
        self.writes = 0

    def commit(self) -> None:
        self.writes += 1

    def add(self, *a, **k) -> None:
        self.writes += 1

    def execute(self, *a, **k):
        raise AssertionError("no DB query expected — forecast_commodity is mocked")


def _build(monkeypatch, *, enabled, fake_forecast=None):
    import app.core.config as cfg
    import app.main as main

    if enabled is None:
        monkeypatch.delenv("ENABLE_ML_FORECAST_API", raising=False)
    else:
        monkeypatch.setenv("ENABLE_ML_FORECAST_API", "true" if enabled else "false")
    cfg._settings = None
    app = main.create_app()

    db = _FakeSession()
    if enabled:
        from app.db.session import get_db

        app.dependency_overrides[get_db] = lambda: db
        if fake_forecast is not None:
            import ml.forecast as mlf

            monkeypatch.setattr(mlf, "forecast_commodity", fake_forecast)
    return TestClient(app), db


def _ok(db, code, *, horizons=(30,), enable_ou=True, **kw):
    return {"commodity_code": code, "available": True, "horizons": {str(horizons[0]): {"model_used": "ou"}}}


def _never(db, code, **kw):
    raise AssertionError("forecast_commodity must not be called for invalid input")


# ── feature flag ─────────────────────────────────────────────────────────────
def test_forecast_disabled_by_default(monkeypatch, clean_settings_cache):
    client, _ = _build(monkeypatch, enabled=None)
    assert client.post("/forecast", json={"commodity_code": "GOLD", "horizon_days": 30}).status_code == 404
    assert client.get("/health").status_code == 200  # always-on endpoints unaffected


def test_forecast_disabled_when_flag_off(monkeypatch, clean_settings_cache):
    client, _ = _build(monkeypatch, enabled=False)
    assert client.post("/forecast", json={"commodity_code": "GOLD", "horizon_days": 30}).status_code == 404


def test_forecast_route_exists_when_flag_on(monkeypatch, clean_settings_cache):
    client, _ = _build(monkeypatch, enabled=True, fake_forecast=_ok)
    r = client.post("/forecast", json={"commodity_code": "GOLD", "horizon_days": 30})
    assert r.status_code == 200
    assert r.json()["available"] is True


# ── input validation ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["..", "../etc", "a.b", "GOLD-1", "A B", "x" * 100, "GOLD/../x"])
def test_forecast_rejects_unsafe_commodity(monkeypatch, clean_settings_cache, bad):
    client, _ = _build(monkeypatch, enabled=True, fake_forecast=_never)
    r = client.post("/forecast", json={"commodity_code": bad, "horizon_days": 30})
    assert r.status_code in (404, 422)  # routing or schema rejects; engine never called
    assert "Traceback" not in r.text and "ml/forecast" not in r.text


@pytest.mark.parametrize("bad_h", [45, 0, -30, 365, 1000])
def test_forecast_rejects_invalid_horizon(monkeypatch, clean_settings_cache, bad_h):
    client, _ = _build(monkeypatch, enabled=True, fake_forecast=_never)
    assert client.post("/forecast", json={"commodity_code": "GOLD", "horizon_days": bad_h}).status_code == 422


def test_forecast_rejects_unknown_fields(monkeypatch, clean_settings_cache):
    client, _ = _build(monkeypatch, enabled=True, fake_forecast=_never)
    r = client.post("/forecast", json={"commodity_code": "GOLD", "horizon_days": 30, "table": "users"})
    assert r.status_code == 422  # extra='forbid'


# ── safe error mapping / no leakage ──────────────────────────────────────────
def test_forecast_engine_error_is_503_without_leak(monkeypatch, clean_settings_cache):
    def boom(db, code, **kw):
        raise RuntimeError("boom secret=postgres://u:p@host/db path=/srv/app/ml/forecast.py")

    client, _ = _build(monkeypatch, enabled=True, fake_forecast=boom)
    r = client.post("/forecast", json={"commodity_code": "GOLD", "horizon_days": 90})
    assert r.status_code == 503
    body = r.text
    for leak in ("boom", "secret", "postgres", "Traceback", "/srv", "forecast.py"):
        assert leak not in body


def test_forecast_unavailable_is_404(monkeypatch, clean_settings_cache):
    def unavail(db, code, **kw):
        return {"available": False, "reason": "need >= 252 positive prices, have 10"}

    client, _ = _build(monkeypatch, enabled=True, fake_forecast=unavail)
    assert client.post("/forecast", json={"commodity_code": "GOLD", "horizon_days": 30}).status_code == 404


# ── no DB write ──────────────────────────────────────────────────────────────
def test_forecast_does_not_write_db(monkeypatch, clean_settings_cache):
    client, db = _build(monkeypatch, enabled=True, fake_forecast=_ok)
    client.post("/forecast", json={"commodity_code": "GOLD", "horizon_days": 30})
    assert db.writes == 0  # endpoint is read-only — no commit/add
