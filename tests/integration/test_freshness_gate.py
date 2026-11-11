"""Unit tests for the config-driven freshness/coverage gate (pure helpers + config load,
no DB/network)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_freshness import classify, is_within_gap, lagging_members, select_groups  # noqa: E402

from etl.ingestion.config import FreshnessGroup, load_freshness_groups  # noqa: E402


def test_is_within_gap_basic() -> None:
    today = date(2026, 6, 30)  # Tuesday
    assert is_within_gap(date(2026, 6, 30), today, 3) is True  # same day
    assert is_within_gap(date(2026, 6, 29), today, 3) is True  # 1 day
    assert is_within_gap(date(2026, 6, 27), today, 3) is True  # 3 days == gap
    assert is_within_gap(date(2026, 6, 26), today, 3) is False  # 4 days > gap
    assert is_within_gap(None, today, 3) is False  # no data ⇒ stale


def test_is_within_gap_catches_the_frozen_incident() -> None:
    # The real incident: futures frozen at 2026-06-24 while it was Sunday 2026-06-28.
    today = date(2026, 6, 28)
    assert is_within_gap(date(2026, 6, 26), today, 3) is True  # Friday close = fresh (2 days)
    assert is_within_gap(date(2026, 6, 24), today, 3) is False  # frozen 4 days = STALE


def test_freshness_config_loads_critical_and_noncritical_groups() -> None:
    groups = {g.name: g for g in load_freshness_groups()}
    assert "futures" in groups and "vn_domestic" in groups
    fut = groups["futures"]
    assert fut.critical is True and fut.max_gap_days >= 1
    assert "GOLD" in fut.commodities and "CRUDE_OIL" in fut.commodities
    vn = groups["vn_domestic"]
    assert vn.critical is False  # scraped spot ⇒ warn, not block the daily gate
    assert "GOLD_VN" in vn.commodities and "SILVER_VN" in vn.commodities


# ETL-VN-4: --group filter + strict classification (pure; no DB/network).

_FUT = FreshnessGroup(name="futures", critical=True, max_gap_days=3, commodities=("GOLD", "CRUDE_OIL"))
_VN = FreshnessGroup(name="vn_domestic", critical=False, max_gap_days=4, commodities=("GOLD_VN", "SILVER_VN"))
_ALL = [_FUT, _VN]


def test_select_groups_none_returns_all() -> None:
    selected, unknown = select_groups(_ALL, None)
    assert [g.name for g in selected] == ["futures", "vn_domestic"]
    assert unknown == []


def test_select_groups_filters_to_named_group() -> None:
    # The VN monitor scopes to vn_domestic only — futures must not leak in.
    selected, unknown = select_groups(_ALL, ["vn_domestic"])
    assert [g.name for g in selected] == ["vn_domestic"]
    assert unknown == []


def test_select_groups_reports_unknown_name() -> None:
    # A typo must surface (caller exits non-zero) — never silently pass green.
    selected, unknown = select_groups(_ALL, ["vn_domestic", "typo_xyz"])
    assert [g.name for g in selected] == ["vn_domestic"]
    assert unknown == ["typo_xyz"]


def test_classify_strict_makes_noncritical_vn_fail() -> None:
    today = date(2026, 7, 4)
    stale = date(2026, 6, 20)  # 14 days > vn max_gap_days=4
    assert classify(_VN, stale, today, strict=False) == "warn"  # daily gate: warn only
    assert classify(_VN, stale, today, strict=True) == "fail"  # VN monitor: red


def test_classify_critical_futures_fail_without_strict() -> None:
    today = date(2026, 7, 4)
    stale = date(2026, 6, 20)
    assert classify(_FUT, stale, today, strict=False) == "fail"  # critical always blocks
    assert classify(_FUT, None, today, strict=False) == "fail"  # no data ⇒ stale ⇒ fail


def test_classify_fresh_is_ok_even_strict() -> None:
    today = date(2026, 7, 4)
    assert classify(_VN, date(2026, 7, 3), today, strict=True) == "ok"
    assert classify(_FUT, date(2026, 7, 3), today, strict=True) == "ok"


def test_lagging_members_names_a_frozen_feed_hidden_by_a_fresh_peer() -> None:
    # One member keeps advancing, so the group max is fresh and the group verdict is OK —
    # the frozen and never-ingested members must still be named.
    today = date(2026, 6, 30)
    by_code = {"GOLD": date(2026, 6, 29), "COCOA": date(2026, 5, 29), "RICE": None}
    assert lagging_members(by_code, today, 3) == [("COCOA", date(2026, 5, 29)), ("RICE", None)]


def test_lagging_members_empty_when_every_member_is_fresh() -> None:
    today = date(2026, 6, 30)
    by_code = {"GOLD": date(2026, 6, 29), "COCOA": date(2026, 6, 27)}
    assert lagging_members(by_code, today, 3) == []


class _StubSession:
    """Answers the per-commodity latest-date query from a dict (no DB)."""

    def __init__(self, latest: dict[str, date]) -> None:
        self._latest = latest

    def execute(self, _stmt, params):  # noqa: ANN001, ANN201
        codes = params["codes"]
        rows = [(c, self._latest[c]) for c in codes if c in self._latest]
        return type("_Result", (), {"all": lambda self: rows})()

    def close(self) -> None:
        pass


def _run_main(monkeypatch, capsys, latest: dict[str, date], groups: list[FreshnessGroup]):  # noqa: ANN001, ANN202
    import app.db.session as db_session
    import check_freshness

    import etl.ingestion.config as ingestion_config

    monkeypatch.setattr(ingestion_config, "load_freshness_groups", lambda: groups)
    monkeypatch.setattr(db_session, "get_session_factory", lambda: lambda: _StubSession(latest))
    code = check_freshness.main([])
    return code, capsys.readouterr()


def test_main_reports_lagging_member_without_changing_group_verdict(monkeypatch, capsys) -> None:  # noqa: ANN001
    today = date.today()
    # CRUDE_OIL has no rows at all; GOLD is current ⇒ group OK (exit 0) but laggard named.
    code, out = _run_main(monkeypatch, capsys, {"GOLD": today}, [_FUT])
    assert code == 0
    assert "OK — futures" in out.out
    assert "LAGGING — futures: 1/2" in out.err and "CRUDE_OIL (latest no data)" in out.err


def test_main_still_fails_when_whole_critical_group_is_stale(monkeypatch, capsys) -> None:  # noqa: ANN001
    code, out = _run_main(monkeypatch, capsys, {}, [_FUT])
    assert code == 1
    assert "STALE — futures" in out.err and "LAGGING" not in out.err
