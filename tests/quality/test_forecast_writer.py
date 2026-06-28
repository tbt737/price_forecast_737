"""Offline unit tests for the shadow forecast-log writer (Phase ACC-1C-A).

No production DB: the forecaster is injected/mocked and the session is a fake that
records calls. Covers dry-run (no insert), --write (insert attempted), row mapping,
business-day target dates, skip-on-failure, idempotent SQL, and safe output.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import write_forecast_log as W  # noqa: E402

SAMPLE = {
    "commodity_code": "ROBUSTA",
    "available": True,
    "last_date": "2026-06-26",
    "last_price": 2000.0,
    "horizons": {
        "30": {
            "model_used": "ou",
            "points": [{"date": "2026-07-01", "value": 1980.0}, {"date": "2026-08-07", "value": 1950.0}],
            "backtest": {"candidates": {"ou": 15.5}, "ou_considered": True, "mape_pct": 15.5, "naive_mape_pct": 23.0, "beats_naive": True},
        },
        "90": {
            "model_used": "naive",
            "points": [{"date": "2026-07-01", "value": 2000.0}, {"date": "2026-10-30", "value": 2000.0}],
            "backtest": {"ou_considered": True, "mape_pct": 7.0, "naive_mape_pct": 7.0, "beats_naive": False},
        },
    },
}


def _sample(code: str) -> dict:
    return {**SAMPLE, "commodity_code": code}


class _Res:
    rowcount = 1


class FakeSession:
    """Records execute() calls; performs no real DB work."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return _Res()

    def begin(self):
        outer = self

        class _Ctx:
            def __enter__(self):
                return outer

            def __exit__(self, *a):
                return False

        return _Ctx()

    def close(self) -> None:
        pass


# ── business-day target dates ────────────────────────────────────────────────
def _bizdays_between(a: date, b: date) -> int:
    n, cur = 0, a
    while cur < b:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def test_business_days_ahead_skips_weekends() -> None:
    fri = date(2026, 6, 26)  # Friday
    assert W.business_days_ahead(fri, 1) == date(2026, 6, 29)  # → Monday
    for n in (30, 90):
        t = W.business_days_ahead(fri, n)
        assert t.weekday() < 5  # lands on a weekday
        assert _bizdays_between(fri, t) == n


# ── forecast → row mapping ───────────────────────────────────────────────────
def test_forecast_to_rows_maps_all_fields() -> None:
    rows = W.forecast_to_rows(SAMPLE, run_id="R1", run_mode="dry_run")
    assert len(rows) == 2
    r30 = next(r for r in rows if r["horizon_days"] == 30)
    assert r30["commodity_code"] == "ROBUSTA"
    assert r30["as_of_date"] == date(2026, 6, 26)
    assert r30["target_date"] == W.business_days_ahead(date(2026, 6, 26), 30)
    assert r30["model_used"] == "ou"
    assert r30["predicted_price"] == 1950.0  # the horizon-end point
    assert r30["baseline_price"] == 2000.0  # naive last value
    assert r30["status"] == "pending"
    assert r30["forecast_run_id"] == "R1"
    md = r30["metadata_json"]
    assert md["ou_considered"] is True and md["source"] == "forecast_commodity" and md["run_mode"] == "dry_run"
    assert md["version"] == W.WRITER_VERSION


def test_forecast_to_rows_skips_unavailable_and_nonpositive() -> None:
    assert W.forecast_to_rows({"available": False, "reason": "x"}, run_id="R", run_mode="dry_run") == []
    assert W.forecast_to_rows({}, run_id="R", run_mode="dry_run") == []
    bad = {
        "commodity_code": "X", "available": True, "last_date": "2026-06-26", "last_price": 100.0,
        "horizons": {"30": {"model_used": "ou", "points": [{"date": "d", "value": -5.0}], "backtest": {}}},
    }
    assert W.forecast_to_rows(bad, run_id="R", run_mode="dry_run") == []


# ── generate_rows: skip-on-failure ───────────────────────────────────────────
def test_generate_rows_skips_failures_without_crashing() -> None:
    def fn(session, code, *, horizons):
        if code == "BOOM":
            raise RuntimeError("upstream")
        if code == "GONE":
            return {"available": False, "reason": "no data"}
        return _sample(code)

    rows, skipped = W.generate_rows(None, ["ROBUSTA", "BOOM", "GONE"], [30, 90], run_id="R", run_mode="dry_run", forecast_fn=fn)
    assert len(rows) == 2  # only ROBUSTA
    assert {c for c, _ in skipped} == {"BOOM", "GONE"}


def test_generate_rows_as_of_guard() -> None:
    rows, skipped = W.generate_rows(
        None, ["ROBUSTA"], [30], run_id="R", run_mode="dry_run",
        as_of=date(2099, 1, 1), forecast_fn=lambda s, c, *, horizons: _sample(c),
    )
    assert rows == [] and skipped[0][0] == "ROBUSTA"


# ── idempotent SQL ───────────────────────────────────────────────────────────
def test_insert_sql_is_idempotent_and_non_destructive() -> None:
    sql = " ".join(W.INSERT_SQL.lower().split())
    assert "insert into fact_forecast_log" in sql
    assert "on conflict (commodity_code, as_of_date, target_date, horizon_days, model_used) do nothing" in sql
    assert "update" not in sql and "delete" not in sql


# ── CLI dry-run vs --write ───────────────────────────────────────────────────
def test_dry_run_default_inserts_nothing(monkeypatch, capsys) -> None:
    fake = FakeSession()
    monkeypatch.setattr(W, "_open_session", lambda: fake)
    monkeypatch.setattr(W, "_default_forecast_fn", lambda s, c, *, horizons: _sample(c))
    assert W.main(["--commodities", "ROBUSTA"]) == 0
    assert fake.executed == []  # NO insert in dry-run
    out = capsys.readouterr().out
    assert "dry-run" in out and "no rows inserted" in out
    assert "postgres" not in out.lower() and "://" not in out  # no DB URL / secret printed


def test_write_flag_attempts_idempotent_insert(monkeypatch) -> None:
    fake = FakeSession()
    monkeypatch.setattr(W, "_open_session", lambda: fake)
    monkeypatch.setattr(W, "_default_forecast_fn", lambda s, c, *, horizons: _sample(c))
    assert W.main(["--commodities", "ROBUSTA", "--write"]) == 0
    assert len(fake.executed) == 2  # one INSERT per horizon
    sql0 = " ".join(fake.executed[0][0].lower().split())
    assert "insert into fact_forecast_log" in sql0 and "do nothing" in sql0


def test_main_rejects_invalid_horizon_and_commodity() -> None:
    assert W.main(["--commodities", "GOLD", "--horizons", "45"]) == 2  # not in {30,90}
    assert W.main(["--commodities", "../etc"]) == 2  # traversal-ish code rejected
