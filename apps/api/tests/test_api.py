"""API tests: health/readiness and the read-only commodity/profile endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


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
    assert len(body) == 16
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
    assert len(r.json()) == 16

    r = client.get("/profiles/gold")
    assert r.status_code == 200
    body = r.json()
    assert body["commodity_code"] == "GOLD"
    assert body["profile"]["commodity_group"] == "metal"
    assert body["version"] == 1
