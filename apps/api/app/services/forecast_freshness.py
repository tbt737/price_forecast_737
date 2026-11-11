"""Staleness annotation for forecast payloads (generic — no per-commodity logic).

The forecaster anchors on the last stored price, whatever its age. A series that
stopped updating months ago (a one-off historical import, a dead scraper) therefore
still yields a well-formed forecast whose "future" dates may already be in the past.
This module adds the age of the anchor to the response so every reader — dashboard,
chat prompt, downstream script — can tell a current forecast from a stale one.

Applied at response time, never stored in the forecast cache: the age grows every
day even while the underlying data (and so the cached forecast) is unchanged.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def data_age_days(last_date: object, today: date) -> int | None:
    """Calendar days from ``last_date`` (ISO string or date) to ``today``; None when
    the anchor date is missing or unparseable. Never negative."""
    if isinstance(last_date, date):
        anchor = last_date
    elif isinstance(last_date, str):
        try:
            anchor = date.fromisoformat(last_date)
        except ValueError:
            return None
    else:
        return None
    return max(0, (today - anchor).days)


def with_data_freshness(result: dict[str, Any], *, today: date, stale_after_days: int) -> dict[str, Any]:
    """Return a COPY of ``result`` carrying ``data_age_days`` and ``data_stale``.

    ``data_stale`` is true when the anchor is more than ``stale_after_days`` calendar
    days old. A payload without a usable ``last_date`` (e.g. ``available: false``) is
    returned unannotated. The input dict is never mutated — it may be a cache entry."""
    age = data_age_days(result.get("last_date"), today)
    if age is None:
        return dict(result)
    return {**result, "data_age_days": age, "data_stale": age > stale_after_days}
