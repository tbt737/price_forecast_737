"""Cold forecasts share work per code without changing cache/auth contracts."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.core.config import get_settings
from app.core.single_flight import KeyedSingleFlight
from app.routers import commodities as routes
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import ml.forecast as forecasts


def database(revision: int = 0) -> MagicMock:
    db = MagicMock(spec=Session)
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(commodity_key=1)
    db.execute.return_value.one.return_value = (10, date(2026, 1, 1), revision)
    return db


@pytest.fixture(autouse=True)
def clean_cache():
    routes._FORECAST_CACHE.clear()
    yield
    routes._FORECAST_CACHE.clear()
    assert not routes._FORECAST_FLIGHTS._entries


def wait_for_follower() -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if routes._FORECAST_FLIGHTS._entries["TEST"].users == 2:
            return
        time.sleep(0.001)
    raise AssertionError("Follower did not join the per-code flight")


def test_same_code_computes_once_and_follower_skips_database(monkeypatch: pytest.MonkeyPatch) -> None:
    started, release = Event(), Event()
    calls = []

    def compute(db, code):
        calls.append(code)
        started.set()
        assert release.wait(5)
        return {"available": False, "commodity_code": code}

    monkeypatch.setattr(forecasts, "forecast_commodity", compute)
    first_db, second_db = database(), database()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(routes.get_commodity_forecast, "test", first_db)
        try:
            assert started.wait(5)
            second = pool.submit(routes.get_commodity_forecast, "TEST", second_db)
            wait_for_follower()
        finally:
            release.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert calls == ["TEST"]
    second_db.execute.assert_not_called()


def test_different_codes_compute_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    together = Barrier(2)

    def compute(db, code):
        together.wait(timeout=5)
        return {"available": False, "commodity_code": code}

    monkeypatch.setattr(forecasts, "forecast_commodity", compute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(routes.get_commodity_forecast, code, database()) for code in ("A", "B")]
        assert [f.result(timeout=5)["commodity_code"] for f in futures] == ["A", "B"]


def test_failed_compute_releases_follower_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    started, release = Event(), Event()
    calls = []

    def compute(db, code):
        calls.append(code)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
            raise RuntimeError("Fixture failure")
        return {"available": False, "commodity_code": code}

    monkeypatch.setattr(forecasts, "forecast_commodity", compute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(routes.get_commodity_forecast, "TEST", database())
        try:
            assert started.wait(5)
            second = pool.submit(routes.get_commodity_forecast, "TEST", database())
            wait_for_follower()
        finally:
            release.set()
        with pytest.raises(HTTPException) as error:
            first.result(timeout=5)
        assert error.value.status_code == 503
        assert second.result(timeout=5)["commodity_code"] == "TEST"
    assert len(calls) == 2
    assert "TEST" in routes._FORECAST_CACHE


def test_revision_change_recomputes_after_fingerprint_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    compute = MagicMock(return_value={"available": False, "commodity_code": "TEST"})
    monkeypatch.setattr(forecasts, "forecast_commodity", compute)
    routes.get_commodity_forecast("TEST", database())
    _, fingerprint, payload = routes._FORECAST_CACHE["TEST"]
    routes._FORECAST_CACHE["TEST"] = (time.monotonic() - routes.FINGERPRINT_TTL - 1, fingerprint, payload)
    routes.get_commodity_forecast("TEST", database(revision=1))
    assert compute.call_count == 2
    assert routes._FORECAST_CACHE["TEST"][1][2] == 1


def test_warm_forecast_does_not_bypass_auth(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "internal_api_key", "fixture-key")
    cached = {"available": False, "commodity_code": "TEST"}
    routes._FORECAST_CACHE["TEST"] = (time.monotonic(), (0, None, 0), cached)
    inner = MagicMock(side_effect=AssertionError("Unauthorized caller reached forecast"))
    monkeypatch.setattr(routes, "_get_commodity_forecast", inner)
    assert client.get("/commodities/TEST/forecast").status_code == 401
    inner.assert_not_called()


def test_lock_registry_does_not_retain_finished_or_failed_keys() -> None:
    flights = KeyedSingleFlight()
    for i in range(100):
        with flights.hold(str(i)):
            assert len(flights._entries) == 1
        assert not flights._entries
    with pytest.raises(ValueError), flights.hold("failure"):
        raise ValueError("fixture")
    assert not flights._entries
