"""Offline unit tests for the forecast accuracy evaluator (Phase ACC-1D-A).

No production DB: the pending rows + actual lookup are mocked and the session is a
fake. Covers exact actual, weekend grace, missing/frozen actual, expiry, dry-run
(no update), targeted/non-destructive SQL, and safe output.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import evaluate_forecast_log as E  # noqa: E402


class _Res:
    rowcount = 1


class FakeSession:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return _Res()

    def rollback(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


ROBUSTA = {
    "forecast_log_id": 1, "commodity_code": "ROBUSTA", "as_of_date": date(2026, 4, 20),
    "target_date": date(2026, 6, 1), "horizon_days": 30, "model_used": "naive", "predicted_price": 20200.0,
}
GOLD = {
    "forecast_log_id": 2, "commodity_code": "GOLD", "as_of_date": date(2026, 5, 15),
    "target_date": date(2026, 6, 26), "horizon_days": 30, "model_used": "ridge_ar", "predicted_price": 4000.0,
}


# ── pure helpers ─────────────────────────────────────────────────────────────
def test_compute_errors() -> None:
    assert E.compute_errors(100.0, 110.0) == (10.0, 10 / 110 * 100)
    assert E.compute_errors(100.0, 0.0) is None
    assert E.compute_errors(100.0, -1.0) is None


def test_nearest_actual_exact_and_weekend_grace() -> None:
    assert E.nearest_actual(
        [(date(2026, 6, 1), 100.0), (date(2026, 6, 2), 101.0)], date(2026, 6, 1), 4
    ) == (date(2026, 6, 1), 100.0)
    # target Saturday 2026-06-27, only Monday 06-29 priced → nearest next within grace
    assert E.nearest_actual([(date(2026, 6, 29), 200.0)], date(2026, 6, 27), 4) == (date(2026, 6, 29), 200.0)


def test_nearest_actual_rejects_beyond_grace_before_target_and_nonpositive() -> None:
    assert E.nearest_actual([(date(2026, 6, 10), 100.0)], date(2026, 6, 1), 4) is None  # 9d > grace
    rows = [(date(2026, 5, 31), 99.0), (date(2026, 6, 1), -5.0), (date(2026, 6, 2), 101.0)]
    assert E.nearest_actual(rows, date(2026, 6, 1), 4) == (date(2026, 6, 2), 101.0)  # skip before + non-positive


def test_decide_evaluated_expired_pending() -> None:
    ev = E.decide(100.0, date(2026, 6, 26), 110.0, date(2026, 6, 29), 7)
    assert ev["status"] == "evaluated" and ev["actual_price"] == 110.0
    assert abs(ev["absolute_error"] - 10.0) < 1e-9
    assert abs(ev["absolute_percentage_error"] - (10 / 110 * 100)) < 1e-9
    assert E.decide(20200.0, date(2026, 6, 1), None, date(2026, 6, 29), 7)["status"] == "expired"  # 28d > 7
    assert E.decide(100.0, date(2026, 6, 27), None, date(2026, 6, 29), 7)["status"] == "pending"  # 2d, recent
    assert E.decide(100.0, date(2026, 6, 27), 0.0, date(2026, 6, 29), 7)["status"] == "pending"  # non-positive actual


def test_stale_row_expires_without_fabricating_actual() -> None:
    d = E.decide(20200.0, date(2026, 6, 1), None, date(2026, 6, 29), 7)
    assert d["status"] == "expired" and "actual_price" not in d


# ── SQL safety ───────────────────────────────────────────────────────────────
def test_select_pending_sql_only_pending_and_due() -> None:
    s = " ".join(E.SELECT_PENDING_SQL.lower().split())
    assert "status = 'pending'" in s and "target_date <= :as_of" in s


def test_update_sql_targeted_and_non_destructive() -> None:
    for sql in (E.UPDATE_EVALUATED_SQL, E.UPDATE_EXPIRED_SQL):
        s = " ".join(sql.lower().split())
        assert "where forecast_log_id = :id and status = 'pending'" in s
        assert "delete" not in s
    assert "'evaluated'" in E.UPDATE_EVALUATED_SQL.lower()
    assert "'expired'" in E.UPDATE_EXPIRED_SQL.lower()


# ── CLI dry-run vs --write ───────────────────────────────────────────────────
def test_dry_run_performs_no_update(monkeypatch, capsys) -> None:
    fake = FakeSession()
    monkeypatch.setattr(E, "_open_session", lambda: fake)
    monkeypatch.setattr(E, "_select_pending", lambda *a, **k: [dict(ROBUSTA)])
    monkeypatch.setattr(E, "_lookup_actual", lambda *a, **k: None)  # frozen — no actual
    assert E.main(["--as-of", "2026-06-29"]) == 0
    assert not any("update" in s.lower() for s, _ in fake.executed)  # dry-run updates nothing
    out = capsys.readouterr().out
    assert "dry-run" in out and "no rows updated" in out
    assert "postgres" not in out.lower() and "://" not in out


def test_write_evaluates_and_expires(monkeypatch) -> None:
    fake = FakeSession()
    monkeypatch.setattr(E, "_open_session", lambda: fake)
    monkeypatch.setattr(E, "_select_pending", lambda *a, **k: [dict(ROBUSTA), dict(GOLD)])
    monkeypatch.setattr(E, "_lookup_actual", lambda s, code, target, grace: 4100.0 if code == "GOLD" else None)
    assert E.main(["--as-of", "2026-06-29", "--write"]) == 0
    sqls = [" ".join(s.lower().split()) for s, _ in fake.executed]
    assert any("status = 'evaluated'" in s for s in sqls)  # GOLD evaluated
    assert any("status = 'expired'" in s for s in sqls)  # ROBUSTA (frozen) expired, not evaluated
    assert all("where forecast_log_id" in s for s in sqls)  # every update targets one row


def test_main_rejects_invalid_horizon_and_commodity() -> None:
    assert E.main(["--horizons", "45"]) == 2
    assert E.main(["--commodities", "../x"]) == 2
