"""Forecast responses carry the age of their anchor price.

A series that stopped updating still yields a well-formed forecast; without an age
signal a months-old anchor is indistinguishable from yesterday's close.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from app.core import config
from app.routers.commodities import _FORECAST_CACHE
from app.services.forecast_freshness import data_age_days, with_data_freshness
from fastapi.testclient import TestClient

TODAY = date(2026, 11, 11)


def test_data_age_days_counts_calendar_days_and_never_goes_negative() -> None:
    assert data_age_days("2026-11-11", TODAY) == 0
    assert data_age_days("2026-11-01", TODAY) == 10
    assert data_age_days(date(2025, 11, 11), TODAY) == 365
    assert data_age_days("2026-11-12", TODAY) == 0  # anchor a timezone ahead of UTC "today"


@pytest.mark.parametrize("bad", [None, "", "not-a-date", 20261111])
def test_data_age_days_is_none_without_a_usable_anchor(bad: object) -> None:
    assert data_age_days(bad, TODAY) is None


def test_stale_flag_flips_strictly_after_the_threshold() -> None:
    at = with_data_freshness({"last_date": "2026-11-01"}, today=TODAY, stale_after_days=10)
    over = with_data_freshness({"last_date": "2026-10-31"}, today=TODAY, stale_after_days=10)
    assert (at["data_age_days"], at["data_stale"]) == (10, False)
    assert (over["data_age_days"], over["data_stale"]) == (11, True)


def test_annotation_copies_and_leaves_the_input_untouched() -> None:
    # The input may be the forecast-cache entry: annotating in place would freeze the
    # age at the first request and serve it for as long as the data stays unchanged.
    cached = {"available": True, "last_date": "2025-06-30"}
    out = with_data_freshness(cached, today=TODAY, stale_after_days=10)
    assert out is not cached and cached == {"available": True, "last_date": "2025-06-30"}
    assert out["data_stale"] is True


def test_unavailable_payload_is_returned_unannotated() -> None:
    out = with_data_freshness({"available": False, "reason": "x"}, today=TODAY, stale_after_days=10)
    assert out == {"available": False, "reason": "x"}


def _stub_forecast(last_date: date):
    def _fn(_db: object, code: str, **_k: object) -> dict:
        return {
            "available": True,
            "commodity_code": code,
            "last_date": last_date.isoformat(),
            "last_price": 100.0,
            "horizons": {},
        }

    return _fn


@pytest.fixture()
def keyed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config.get_settings(), "internal_api_key", "k")
    _FORECAST_CACHE.clear()
    yield {"X-Internal-Key": "k"}
    _FORECAST_CACHE.clear()


def test_forecast_endpoint_flags_a_stale_anchor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, keyed: dict[str, str]
) -> None:
    import ml.forecast as mlf

    today = datetime.now(UTC).date()
    monkeypatch.setattr(mlf, "forecast_commodity", _stub_forecast(today - timedelta(days=400)))
    body = client.get("/commodities/GOLD/forecast", headers=keyed).json()
    assert body["data_age_days"] == 400 and body["data_stale"] is True

    # Warm cache hit: still annotated, and the cached entry itself stays clean.
    again = client.get("/commodities/GOLD/forecast", headers=keyed).json()
    assert again["data_stale"] is True
    assert "data_age_days" not in _FORECAST_CACHE["GOLD"][2]


def test_forecast_endpoint_reports_a_current_anchor_as_fresh(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, keyed: dict[str, str]
) -> None:
    import ml.forecast as mlf

    today = datetime.now(UTC).date()
    monkeypatch.setattr(mlf, "forecast_commodity", _stub_forecast(today - timedelta(days=1)))
    body = client.get("/commodities/GOLD/forecast", headers=keyed).json()
    assert body["data_age_days"] == 1 and body["data_stale"] is False


def test_stale_threshold_comes_from_settings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, keyed: dict[str, str]
) -> None:
    import ml.forecast as mlf

    today = datetime.now(UTC).date()
    monkeypatch.setattr(mlf, "forecast_commodity", _stub_forecast(today - timedelta(days=5)))
    monkeypatch.setattr(config.get_settings(), "forecast_stale_after_days", 3)
    assert client.get("/commodities/GOLD/forecast", headers=keyed).json()["data_stale"] is True
