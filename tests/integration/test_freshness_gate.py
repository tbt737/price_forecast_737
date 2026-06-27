"""Unit tests for the daily-ingest freshness gate (pure helpers, no DB/network)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_freshness import is_fresh, previous_business_day  # noqa: E402


def test_previous_business_day_skips_weekend() -> None:
    assert previous_business_day(date(2026, 6, 28)) == date(2026, 6, 26)  # Sun → Fri
    assert previous_business_day(date(2026, 6, 29)) == date(2026, 6, 26)  # Mon → Fri
    assert previous_business_day(date(2026, 6, 30)) == date(2026, 6, 29)  # Tue → Mon


def test_is_fresh_detects_the_stale_incident() -> None:
    today = date(2026, 6, 28)  # Sunday → expected latest = Fri 2026-06-26
    assert is_fresh(date(2026, 6, 26), today) is True  # Friday close = fresh
    assert is_fresh(date(2026, 6, 24), today) is False  # the bug: frozen at 06-24 = STALE
    assert is_fresh(None, today) is False  # no data at all = stale


def test_is_fresh_passes_when_current_midweek() -> None:
    today = date(2026, 6, 30)  # Tuesday → expected latest = Mon 2026-06-29
    assert is_fresh(date(2026, 6, 29), today) is True
    assert is_fresh(date(2026, 6, 30), today) is True  # today's data also acceptable
    assert is_fresh(date(2026, 6, 26), today) is False  # 3 days stale
