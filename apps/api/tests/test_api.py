"""API tests: health/readiness and the read-only commodity/profile endpoints."""

from __future__ import annotations

from datetime import date

import pytest
from app.models import DimCommodity, DimMarketInstrument, FactPriceDaily
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready_db_up(client: TestClient) -> None:
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": "up"}


def test_list_commodities(client: TestClient) -> None:
    r = client.get("/commodities")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 20  # +GOLD_VN +SILVER_VN
    codes = {c["commodity_code"] for c in body}
    assert {"ROBUSTA", "GOLD", "CRUDE_OIL", "FREIGHT_INDICES"}.issubset(codes)


def test_get_commodity_detail_with_instruments(client: TestClient) -> None:
    r = client.get("/commodities/robusta")  # case-insensitive
    assert r.status_code == 200
    body = r.json()
    assert body["commodity_code"] == "ROBUSTA"
    assert any(i["instrument_code"] == "ICE_RC" for i in body["instruments"])


def test_get_commodity_unknown_404(client: TestClient) -> None:
    assert client.get("/commodities/NOT_A_COMMODITY").status_code == 404


def test_list_and_get_profiles(client: TestClient) -> None:
    r = client.get("/profiles")
    assert r.status_code == 200
    assert len(r.json()) == 20  # +GOLD_VN +SILVER_VN

    r = client.get("/profiles/gold")
    assert r.status_code == 200
    body = r.json()
    assert body["commodity_code"] == "GOLD"
    assert body["profile"]["commodity_group"] == "metal"
    assert body["version"] == 1


def test_stats(client: TestClient) -> None:
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"commodities", "profiles", "instruments", "regions", "data_sources", "fact_rows"}
    assert body["commodities"] == 20  # +GOLD_VN +SILVER_VN
    assert body["profiles"] == 20
    assert body["instruments"] > 0
    assert body["fact_rows"] == 0  # no ingestion yet


def test_commodity_prices_series(client: TestClient, seeded_session: Session) -> None:
    com = seeded_session.execute(select(DimCommodity).filter_by(commodity_code="GOLD")).scalar_one()
    inst = seeded_session.execute(select(DimMarketInstrument).filter_by(instrument_code="COMEX_GC")).scalar_one()
    seeded_session.add_all(
        [
            FactPriceDaily(
                commodity_key=com.commodity_key, market_instrument_key=inst.market_instrument_key,
                price_date=date(2025, 1, 2), release_date=date(2025, 1, 3), value=100, currency="USD", revision=0,
            ),
            FactPriceDaily(
                commodity_key=com.commodity_key, market_instrument_key=inst.market_instrument_key,
                price_date=date(2025, 1, 3), release_date=date(2025, 1, 4), value=101.5, currency="USD", revision=0,
            ),
        ]
    )
    seeded_session.commit()

    r = client.get("/commodities/gold/prices?days=20000")  # max allowed lookback ⇒ returns all history
    assert r.status_code == 200
    body = r.json()
    assert body["commodity_code"] == "GOLD"
    assert body["instrument_code"] == "COMEX_GC"
    assert body["currency"] == "USD"
    assert [p["value"] for p in body["points"]] == [100.0, 101.5]
    assert body["points"][0]["date"] == "2025-01-02"


def test_commodity_prices_empty_and_unknown(client: TestClient) -> None:
    empty = client.get("/commodities/CORN/prices")  # no facts in test DB
    assert empty.status_code == 200 and empty.json()["points"] == []
    assert client.get("/commodities/NOT_A_COMMODITY/prices").status_code == 404


def test_commodity_forecast_unavailable_without_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # /forecast is gated (SEC-2): provision the internal key + send the header the way
    # cqp-web does, then GOLD (no price history in the test DB) → available: false.
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "internal_api_key", "test-key")
    hdr = {"X-Internal-Key": "test-key"}
    r = client.get("/commodities/GOLD/forecast", headers=hdr)
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert client.get("/commodities/NOT_A_COMMODITY/forecast", headers=hdr).status_code == 404


def test_dashboard_root_serves_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Multi-Commodity Quant Forecasting" in r.text
