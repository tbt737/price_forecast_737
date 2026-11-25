"""Unit tests for the config-driven freshness/coverage gate (pure helpers + config load,
no DB/network)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import check_freshness  # noqa: E402
import pytest  # noqa: E402
from check_freshness import (  # noqa: E402
    classify,
    group_latest,
    is_within_gap,
    select_groups,
    stale_members,
)

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


# Per-commodity staleness: one live member must not hide a dead one in the same group.

_TODAY = date(2026, 7, 4)
_LIVE, _DEAD = date(2026, 7, 3), date(2026, 5, 1)


def test_stale_members_finds_dead_series_behind_a_live_one() -> None:
    latest = {"GOLD_VN": _DEAD, "SILVER_VN": _LIVE}
    assert group_latest(_VN, latest) == _LIVE  # the group itself still looks fresh
    assert classify(_VN, group_latest(_VN, latest), _TODAY, strict=True) == "ok"
    assert stale_members(_VN, latest, _TODAY) == [("GOLD_VN", _DEAD)]


def test_stale_members_treats_a_member_without_rows_as_stale() -> None:
    assert stale_members(_VN, {"SILVER_VN": _LIVE}, _TODAY) == [("GOLD_VN", None)]
    assert stale_members(_VN, {"GOLD_VN": _LIVE, "SILVER_VN": _LIVE}, _TODAY) == []
    assert group_latest(_VN, {}) is None


class _NullSession:
    def close(self) -> None:
        pass


def _run_gate(monkeypatch: pytest.MonkeyPatch, latest: dict[str, date], argv: list[str]) -> int:
    import app.db.session as db_session

    import etl.ingestion.config as ingestion_config

    class _FrozenDate(date):
        @classmethod
        def today(cls) -> date:
            return _TODAY

    monkeypatch.setattr(ingestion_config, "load_freshness_groups", lambda: list(_ALL))
    monkeypatch.setattr(db_session, "get_session_factory", lambda: _NullSession)
    monkeypatch.setattr(check_freshness, "date", _FrozenDate)
    monkeypatch.setattr(
        check_freshness, "_latest_dates", lambda _s, codes: {c: latest[c] for c in codes if c in latest}
    )
    return check_freshness.main(argv)


def test_gate_warns_on_stale_member_and_strict_turns_it_red(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    latest = {"GOLD": _LIVE, "CRUDE_OIL": _LIVE, "GOLD_VN": _DEAD, "SILVER_VN": _LIVE}
    # Daily gate: every group advanced ⇒ still green, but the dead series is named.
    assert _run_gate(monkeypatch, latest, []) == 0
    assert "STALE MEMBER — vn_domestic/GOLD_VN" in capsys.readouterr().err
    # Dedicated VN monitor (--strict): a dead member is a failure.
    assert _run_gate(monkeypatch, latest, ["--group", "vn_domestic", "--strict"]) == 1


def test_gate_stays_green_and_quiet_when_every_member_is_fresh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    latest = {"GOLD": _LIVE, "CRUDE_OIL": _LIVE, "GOLD_VN": _LIVE, "SILVER_VN": _LIVE}
    assert _run_gate(monkeypatch, latest, ["--strict"]) == 0
    assert capsys.readouterr().err == ""


def test_gate_fully_stale_critical_group_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    latest = {"GOLD": _DEAD, "CRUDE_OIL": _DEAD, "GOLD_VN": _LIVE, "SILVER_VN": _LIVE}
    assert _run_gate(monkeypatch, latest, []) == 1


def test_monitored_commodities_are_real_profiles_listed_once() -> None:
    # A typo here is silent at runtime: the code simply never matches a row.
    import yaml

    profiles = Path(__file__).resolve().parents[2] / "configs" / "commodities"
    known = {yaml.safe_load(p.read_text(encoding="utf-8"))["commodity_code"] for p in profiles.glob("*.yaml")}
    monitored = [code for g in load_freshness_groups() for code in g.commodities]
    assert not sorted(set(monitored) - known)
    assert len(monitored) == len(set(monitored))
