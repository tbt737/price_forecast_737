"""Unit tests for the config-driven freshness/coverage gate (pure helpers + config load,
no DB/network)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_freshness import is_within_gap  # noqa: E402

from etl.ingestion.config import load_freshness_groups  # noqa: E402


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
