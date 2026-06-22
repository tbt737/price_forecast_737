"""Integration: FixtureSource safety + end-to-end fixture → plan_batch → report."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from app.models import (
    FactEventRisk,
    FactLogisticsPeriodic,
    FactMacroDaily,
    FactPriceDaily,
    FactSupplyDemandPeriodic,
    FactWeatherDaily,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.report import plan_batch
from etl.resolution import ReferenceResolver
from etl.sources.fixture import FIXTURE_ROOT, FixtureError, FixtureSource, all_family_fixtures, load_family_fixture

FACT_MODELS = (
    FactPriceDaily, FactWeatherDaily, FactMacroDaily,
    FactLogisticsPeriodic, FactSupplyDemandPeriodic, FactEventRisk,
)


# ── Safety guards ────────────────────────────────────────────────────────────
def test_path_traversal_rejected() -> None:
    with pytest.raises(FixtureError):
        FixtureSource(FactFamily.macro_daily, "../../../../etc/passwd.json")


def test_absolute_escape_rejected(tmp_path: Path) -> None:
    with pytest.raises(FixtureError):
        FixtureSource(FactFamily.macro_daily, str(tmp_path / "outside.json"))


def test_unsupported_extension_rejected() -> None:
    with pytest.raises(FixtureError):
        FixtureSource(FactFamily.macro_daily, "price_daily.csv")


def test_malformed_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ", encoding="utf-8")
    src = FixtureSource(FactFamily.macro_daily, "bad.json", root=tmp_path)
    with pytest.raises(FixtureError):
        list(src.collect())


def test_collect_parses_real_fixture() -> None:
    records = list(load_family_fixture(FactFamily.price_daily).collect())
    assert records and all(isinstance(r, NormalizedRecord) for r in records)
    assert records[0].family is FactFamily.price_daily
    assert records[0].observation_date is not None  # ISO string parsed to date


def test_every_family_has_a_fixture_file() -> None:
    for fam in FactFamily:
        assert (FIXTURE_ROOT / f"{fam.value}.json").is_file()


# ── End-to-end fixture flow ──────────────────────────────────────────────────
def _all_fixture_records() -> list[NormalizedRecord]:
    records: list[NormalizedRecord] = []
    for source in all_family_fixtures():
        records.extend(source.collect())
    return records


def test_fixture_batch_plan_counts_and_no_persist(profiles_session: Session) -> None:
    records = _all_fixture_records()
    report = plan_batch(profiles_session, records, source_code="manual")

    assert report.total == 18
    assert report.would_insert == 12  # valid rows
    assert report.rejected == 6  # invalid rows
    assert report.conflicts == 0

    # every invalid kind is represented
    assert {"UNKNOWN_INSTRUMENT", "UNKNOWN_REGION", "MISSING_RELEASE_DATE",
            "INVALID_PERIOD_RANGE", "UNKNOWN_SOURCE", "UNKNOWN_COMMODITY"} <= set(report.by_error_code)
    # the `note` field on a valid price row surfaces as a warning, not an error
    assert "IGNORED_FIELD" in report.by_warning_code

    # JSON-safe + leak-safe
    blob = json.dumps(report.to_dict())
    assert "payload" not in blob and "commodity_key" not in blob

    # dry-run persisted nothing
    for model in FACT_MODELS:
        assert profiles_session.scalar(select(func.count()).select_from(model)) == 0


def test_fixture_conflict_row_becomes_conflict_plan(profiles_session: Session) -> None:
    # Resolve the keys for the valid ROBUSTA supply/demand fixture row and persist it.
    rec = NormalizedRecord(
        family=FactFamily.supply_demand_periodic, data_source_code="manual",
        release_date=date(2025, 2, 10), commodity_code="ROBUSTA", metric_code="ending_stocks",
        period_start=date(2025, 1, 1), period_end=date(2025, 1, 31), value=100,
    )
    res = ReferenceResolver(profiles_session).resolve(rec)
    profiles_session.add(
        FactSupplyDemandPeriodic(
            commodity_key=res.commodity_key, data_source_key=res.data_source_key,
            metric_code="ending_stocks", period_start=rec.period_start, period_end=rec.period_end,
            release_date=rec.release_date, revision=0, value=100,
        )
    )
    profiles_session.commit()

    # The matching fixture row now plans as a conflict (not would_insert).
    report = plan_batch(profiles_session, [rec], source_code="manual")
    assert report.conflicts == 1
    assert report.would_insert == 0
    assert report.items[0]["conflict"] is True
