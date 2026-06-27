"""Phase 7B — the experimental ML model-registry router is gated by
``ENABLE_ML_MODELS_API`` (default OFF). These tests pin the disabled-by-default
behaviour and the on/off toggle. No DB, no network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def clean_settings_cache():
    """Reset the cached Settings before and after so each test re-reads the env."""
    import app.core.config as cfg

    cfg._settings = None
    yield
    cfg._settings = None


def _app(monkeypatch, *, enabled: bool | None):
    import app.core.config as cfg
    import app.main as main

    if enabled is None:
        monkeypatch.delenv("ENABLE_ML_MODELS_API", raising=False)  # rely on the default
    else:
        monkeypatch.setenv("ENABLE_ML_MODELS_API", "true" if enabled else "false")
    cfg._settings = None  # force the flag to be re-read from the env
    return main.create_app()


def test_models_api_disabled_by_default(monkeypatch, clean_settings_cache):
    """With no env override, the flag defaults to False ⇒ /models is not mounted."""
    client = TestClient(_app(monkeypatch, enabled=None))
    assert client.get("/models").status_code == 404
    # the always-on endpoints are unaffected
    assert client.get("/health").status_code == 200


def test_models_api_disabled_when_flag_off(monkeypatch, clean_settings_cache):
    client = TestClient(_app(monkeypatch, enabled=False))
    assert client.get("/models").status_code == 404


def test_models_api_enabled_when_flag_on(monkeypatch, clean_settings_cache):
    client = TestClient(_app(monkeypatch, enabled=True))
    resp = client.get("/models")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)  # registry list (empty when no models registered)


@pytest.mark.parametrize("bad", ["..", "../etc", "a.b", "GOLD-1", "A B", "x" * 100])
def test_best_model_rejects_unsafe_codes(monkeypatch, clean_settings_cache, bad):
    """Traversal/invalid commodity codes must fail safely — never 200, never 500,
    no internal path or traceback leaked."""
    client = TestClient(_app(monkeypatch, enabled=True))
    resp = client.get(f"/commodities/{bad}/models/best")
    assert resp.status_code in (400, 404)  # rejected by routing or validation
    body = resp.text
    assert "Traceback" not in body and "data/models" not in body and "/registry" not in body


def test_best_model_valid_but_unregistered_is_404(monkeypatch, clean_settings_cache):
    client = TestClient(_app(monkeypatch, enabled=True))
    resp = client.get("/commodities/GOLD/models/best")
    assert resp.status_code == 404  # valid code, no registered model ⇒ safe 404


def test_best_model_endpoint_absent_when_flag_off(monkeypatch, clean_settings_cache):
    client = TestClient(_app(monkeypatch, enabled=None))
    assert client.get("/commodities/GOLD/models/best").status_code == 404  # router not mounted
