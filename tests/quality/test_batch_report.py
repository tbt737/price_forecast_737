"""Pure tests for NormalizedRecord.from_dict and the BatchPlanReport (no DB)."""

from __future__ import annotations

import json
from datetime import date

from etl.contracts import FactFamily, NormalizedRecord
from etl.planner import InsertPlan
from etl.report import BatchPlanReport
from etl.validation import ErrorCode, Severity, ValidationIssue, validate_record


# ── from_dict ────────────────────────────────────────────────────────────────
def test_from_dict_parses_iso_dates() -> None:
    rec = NormalizedRecord.from_dict(
        FactFamily.supply_demand_periodic,
        {"commodity_code": "ROBUSTA", "data_source_code": "manual", "metric_code": "ending_stocks",
         "period_start": "2025-01-01", "period_end": "2025-01-31", "release_date": "2025-02-10", "value": 100},
    )
    assert rec.period_start == date(2025, 1, 1)
    assert rec.period_end == date(2025, 1, 31)
    assert rec.release_date == date(2025, 2, 10)
    assert rec.commodity_code == "ROBUSTA"


def test_from_dict_records_ignored_fields_as_warning() -> None:
    rec = NormalizedRecord.from_dict(
        FactFamily.macro_daily,
        {"data_source_code": "manual", "observation_date": "2025-01-10", "release_date": "2025-01-10",
         "indicator_code": "dxy", "totally_unknown": 1},
    )
    assert rec.attributes["_ignored_fields"] == ["totally_unknown"]
    warnings = validate_record(rec).warnings
    assert any(w.code is ErrorCode.IGNORED_FIELD for w in warnings)


def test_from_dict_malformed_date_is_error() -> None:
    rec = NormalizedRecord.from_dict(
        FactFamily.macro_daily,
        {"data_source_code": "manual", "observation_date": "not-a-date", "release_date": "2025-01-10",
         "indicator_code": "dxy"},
    )
    assert rec.observation_date is None
    result = validate_record(rec)
    assert not result.ok
    assert ErrorCode.INVALID_DATE in result.error_codes


# ── BatchPlanReport ──────────────────────────────────────────────────────────
def _rec(family: FactFamily = FactFamily.macro_daily) -> NormalizedRecord:
    return NormalizedRecord(
        family=family, data_source_code="manual", release_date=date(2025, 1, 10),
        observation_date=date(2025, 1, 10), indicator_code="dxy",
    )


def _plan(*, errors=None, conflict=False, target="fact_macro_daily") -> InsertPlan:
    errs = errors or []
    return InsertPlan(
        record=_rec(),
        target_table=target,
        resolved_keys={"commodity_key": 7, "data_source_key": 3},  # must NOT leak into report
        payload={"value": 104.2} if not errs else None,
        grain={"indicator_code": "dxy"},
        errors=errs,
        conflict=None if errs else conflict,
    )


def test_report_totals_and_breakdowns() -> None:
    plans = [
        _plan(),  # would_insert
        _plan(conflict=True),  # conflict
        _plan(errors=[ValidationIssue(ErrorCode.MISSING_SOURCE, "x")]),  # rejected
    ]
    report = BatchPlanReport.from_plans(plans, source_code="manual")
    assert report.total == 3
    assert report.would_insert == 1
    assert report.conflicts == 1
    assert report.rejected == 1
    assert report.by_target["fact_macro_daily"] == 3
    assert report.by_error_code["MISSING_SOURCE"] == 1
    assert report.by_family["macro_daily"]["planned"] == 3


def test_report_to_dict_is_json_safe() -> None:
    report = BatchPlanReport.from_plans([_plan(), _plan(conflict=True)], source_code="manual")
    dumped = json.dumps(report.to_dict())  # must not raise
    assert '"totals"' in dumped


def test_report_does_not_leak_payload_or_keys() -> None:
    report = BatchPlanReport.from_plans([_plan()], source_code="manual")
    blob = json.dumps(report.to_dict())
    assert "payload" not in blob
    assert "resolved_keys" not in blob
    assert "104.2" not in blob  # raw value must not appear
    assert "commodity_key" not in blob  # resolved FK must not appear
    for item in report.to_dict()["items"]:
        assert set(item) == {"index", "family", "target_table", "would_insert", "conflict",
                             "error_codes", "warning_codes"}


def test_summary_is_one_screen_text() -> None:
    report = BatchPlanReport.from_plans([_plan(), _plan(errors=[ValidationIssue(ErrorCode.MISSING_SOURCE, "x")])])
    text = report.summary()
    assert isinstance(text, str)
    assert "would-insert" in text and "rejected" in text


def test_warning_issue_severity_default() -> None:
    assert ValidationIssue(ErrorCode.IGNORED_FIELD, "x", Severity.warning).severity is Severity.warning
