"""Integration: automated ingestion connectors + orchestration (no network)."""

from __future__ import annotations

from datetime import date

from app.models import FactPriceDaily, FactWeatherDaily
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from etl.backfill import backfill
from etl.ingestion.config import PriceSpec, WeatherSpec, load_ingestion_config
from etl.provenance import gate_record
from etl.sources.market.yahoo import YahooPriceSource
from etl.sources.weather.nasa_power import NasaPowerSource
from etl.writer import write_batch


def _price_fetch(ticker: str, period: str):
    return [{"date": date(2025, 1, 2), "close": 100.0}, {"date": date(2025, 1, 3), "close": 101.5}]


def _weather_fetch(lat, lon, start, end, params):
    return {"T2M": {date(2025, 1, 1): 25.0, date(2025, 1, 2): 26.0}, "PRECTOTCORR": {date(2025, 1, 1): 3.2}}


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# ── config ────────────────────────────────────────────────────────────────────
def test_ingestion_config_loads_real_registry() -> None:
    cfg = load_ingestion_config()
    assert cfg.prices and cfg.weather
    assert {"yahoo", "NASA_POWER"} <= cfg.source_codes
    gold = next(p for p in cfg.prices if p.commodity_code == "GOLD")
    assert gold.ticker == "GC=F" and gold.instrument_code == "COMEX_GC"


# ── connectors produce well-formed records with provenance ────────────────────
def test_yahoo_connector_builds_records_with_provenance() -> None:
    spec = PriceSpec("ALPHA", "INST1", "ZC=F", "USD", "manual", release_lag_days=1)
    records = list(YahooPriceSource([spec], fetch=_price_fetch).collect())
    assert len(records) == 2
    r = records[0]
    assert r.commodity_code == "ALPHA" and r.instrument_code == "INST1"
    assert r.observation_date == date(2025, 1, 2) and r.release_date == date(2025, 1, 3)
    assert r.source_record_id == "manual:ZC=F:2025-01-02"  # id prefix = the spec's source_code
    assert gate_record(r) == []  # passes the connector provenance gate


def test_nasa_connector_maps_metrics_with_provenance() -> None:
    spec = WeatherSpec("ALPHA", "REG1", 12.7, 108.1, "NASA_POWER", 3, {"T2M": "temp_mean", "PRECTOTCORR": "precip"})
    source = NasaPowerSource([spec], start=date(2025, 1, 1), end=date(2025, 1, 2), fetch=_weather_fetch)
    records = list(source.collect())
    metrics = {r.metric_code for r in records}
    assert metrics == {"temp_mean", "precip"}
    assert all(gate_record(r) == [] for r in records)
    assert all(r.region_code == "REG1" for r in records)


# ── full write path: connector → gate → write_batch, idempotent replay ────────
def test_yahoo_ingest_writes_then_replays_idempotent(seeded_session: Session) -> None:
    spec = PriceSpec("ALPHA", "INST1", "ZC=F", "USD", "manual", release_lag_days=1)
    source = YahooPriceSource([spec], fetch=_price_fetch)

    report = write_batch(seeded_session, source.gate().accepted, dry_run=False)
    assert report.inserted == 2 and report.committed is True
    assert _count(seeded_session, FactPriceDaily) == 2

    replay_records = YahooPriceSource([spec], fetch=_price_fetch).gate().accepted
    replay = write_batch(seeded_session, replay_records, dry_run=False)
    assert replay.idempotent == 2 and replay.inserted == 0
    assert _count(seeded_session, FactPriceDaily) == 2  # no duplicates


def test_backfill_bulk_insert_is_idempotent(seeded_session: Session) -> None:
    spec = PriceSpec("ALPHA", "INST1", "ZC=F", "USD", "manual", release_lag_days=1)

    def many_fetch(ticker: str, period: str):
        return [{"date": date(2024, 1, d), "close": 100.0 + d} for d in range(1, 11)]  # 10 distinct days

    backfill(seeded_session, connectors=[YahooPriceSource([spec], fetch=many_fetch)])
    assert _count(seeded_session, FactPriceDaily) == 10

    # re-run: ON CONFLICT DO NOTHING → no duplicates
    report = backfill(seeded_session, connectors=[YahooPriceSource([spec], fetch=many_fetch)])
    assert report["inserted_total"] == 0
    assert _count(seeded_session, FactPriceDaily) == 10


def test_nasa_ingest_writes_weather(seeded_session: Session) -> None:
    # source_code 'manual' is seeded in the test session (real NASA_POWER is seeded in prod).
    spec = WeatherSpec("ALPHA", "REG1", 12.7, 108.1, "manual", 3, {"T2M": "temp_mean", "PRECTOTCORR": "precip"})
    source = NasaPowerSource([spec], start=date(2025, 1, 1), end=date(2025, 1, 2), fetch=_weather_fetch)
    report = write_batch(seeded_session, source.gate().accepted, dry_run=False)
    assert report.inserted == 3 and report.committed is True  # 2 temp + 1 precip
    assert _count(seeded_session, FactWeatherDaily) == 3
