"""Restatement-aware reconcile for date-range price-history sources (VN-STOCKS heal).

An ADJUSTED price feed rewrites its ENTIRE history whenever a corporate action
occurs (dividend/split), while the platform's fact tables are append-only. This
module closes that gap using the schema's own intended mechanism — the ``revision``
grain column ("a revised series gets a new row, never an UPDATE"):

  1. fetch a short recent window per instrument and compare the overlapping dates
     (anchors) with what is stored at the instrument's LATEST revision;
  2. anchors match  → append only the genuinely new dates, at that same revision;
  3. anchors differ → the source restated: refetch the FULL history and insert the
     complete series at ``max(revision) + 1`` in ONE atomic transaction (older
     revisions are kept — the point-in-time audit trail stays intact);
  4. no overlap     → fail closed: write nothing (a deep backfill / wider window is
     the operator's explicit move, never an implicit one).

Single-basis rule: every read path selects ONLY the instrument's latest revision
(see ``ml.forecast.load_price_series`` and the API price series endpoint), so a
mixed old/new-basis series can never be served.

Dry-run by default (INV-7): ``dry_run=False`` is the only way anything persists.
No network here — the connector (``etl.sources.market.vn_stocks``) stays the
sanctioned network boundary and its ``fetch`` is injectable for offline tests.
Inserts use plain add_all + one commit per instrument — NO conflict suppression:
a duplicate grain inside a reload/append is a bug and must abort loudly.
"""

from __future__ import annotations

import calendar
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

_API_DIR = Path(__file__).resolve().parent.parent / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from etl.conflicts import TARGET_MODELS  # noqa: E402
from etl.contracts import FactFamily, NormalizedRecord  # noqa: E402
from etl.ingestion.config import StockReconcileConfig, VnStockSpec  # noqa: E402
from etl.planner import build_payload  # noqa: E402
from etl.resolution import ReferenceResolver  # noqa: E402
from etl.sources.market.vn_stocks import StockFetch, VnStockHistorySource  # noqa: E402
from etl.validation import validate_record  # noqa: E402


def _ts(d: date) -> int:
    return calendar.timegm(d.timetuple())


def _stored_series(session: Session, spec: VnStockSpec) -> tuple[int | None, dict[date, float]]:
    """(latest revision, {price_date: value}) stored for the spec's instrument at that
    revision — the canonical single-basis series. (None, {}) when nothing is stored."""
    from app.models import DimCommodity, DimMarketInstrument, FactPriceDaily

    row = session.execute(
        select(DimCommodity.commodity_key, DimMarketInstrument.market_instrument_key)
        .join(DimMarketInstrument, DimMarketInstrument.commodity_key == DimCommodity.commodity_key)
        .where(
            DimCommodity.commodity_code == spec.commodity_code,
            DimMarketInstrument.instrument_code == spec.instrument_code,
        )
    ).first()
    if row is None:
        return None, {}
    commodity_key, instrument_key = row
    latest = session.execute(
        select(func.max(FactPriceDaily.revision)).where(
            FactPriceDaily.commodity_key == commodity_key,
            FactPriceDaily.market_instrument_key == instrument_key,
        )
    ).scalar_one_or_none()
    if latest is None:
        return None, {}
    rows = session.execute(
        select(FactPriceDaily.price_date, FactPriceDaily.value).where(
            FactPriceDaily.commodity_key == commodity_key,
            FactPriceDaily.market_instrument_key == instrument_key,
            FactPriceDaily.revision == latest,
            FactPriceDaily.value.is_not(None),
        )
    ).all()
    return int(latest), {r.price_date: float(r.value) for r in rows}


def _fetch_records(
    spec: VnStockSpec, *, date_from: date, date_to: date, fetch: StockFetch | None
) -> list[NormalizedRecord]:
    """Collect + provenance-gate the spec's records over [date_from, date_to]."""
    source = VnStockHistorySource([spec], date_from=_ts(date_from), date_to=_ts(date_to), fetch=fetch)
    return list(source.gate().accepted)


def _payloads(
    session: Session, resolver: ReferenceResolver, records: list[NormalizedRecord]
) -> tuple[list[dict[str, Any]], int]:
    """(valid payloads, invalid count) — validation + key resolution, exactly like the
    bulk backfill path builds its rows."""
    out: list[dict[str, Any]] = []
    invalid = 0
    for record in records:
        spec_ = record.spec()
        resolution = resolver.resolve(record)
        validation = validate_record(record)
        if spec_ is None or validation.errors or resolution.issues:
            invalid += 1
            continue
        out.append(build_payload(record, resolution, spec_))
    return out, invalid


def _atomic_insert(session: Session, family: FactFamily, payloads: list[dict[str, Any]]) -> None:
    """All-or-nothing insert with NO conflict suppression: a duplicate grain here is a
    bug (or a concurrent writer) and must roll the whole instrument back loudly."""
    model = TARGET_MODELS[family]
    try:
        session.add_all(model(**p) for p in payloads)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise


def _max_abs_return_pct(closes: list[tuple[date, float]]) -> float:
    """Largest |day-over-day return| (%) across consecutive closes, 0.0 if < 2 points."""
    ordered = sorted(closes)
    worst = 0.0
    for (_, prev), (_, cur) in zip(ordered, ordered[1:], strict=False):
        if prev > 0:
            worst = max(worst, abs(cur / prev - 1.0) * 100.0)
    return worst


def reconcile_stock_history(
    session: Session,
    specs: list[VnStockSpec],
    *,
    today: date,
    config: StockReconcileConfig | None = None,
    history_days: int = 10,
    fetch: StockFetch | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Reconcile every spec's stored series against the source (see module docstring).

    Returns a JSON-able report; per-instrument statuses:
      ``empty`` | ``no_anchor`` | ``fresh`` | ``appended``/``would_append`` |
      ``restated``/``would_restate`` | ``error`` (fail-closed; nothing persisted).
    """
    cfg = config or StockReconcileConfig()
    deep_from = date.fromisoformat(cfg.deep_from)
    resolver = ReferenceResolver(session)
    items: list[dict[str, Any]] = []

    for spec in specs:
        item: dict[str, Any] = {
            "commodity_code": spec.commodity_code,
            "instrument_code": spec.instrument_code,
            "warnings": [],
        }
        items.append(item)

        latest_rev, stored = _stored_series(session, spec)
        if latest_rev is None or not stored:
            # Nothing stored yet: the initial deep backfill is a deliberate operator
            # step (prod sequence step 8), never a side effect of the daily reconcile.
            item["status"] = "empty"
            continue

        # Window ALWAYS reaches back to the stored tail (minus a small buffer) — a
        # fixed N-day window would go permanently `no_anchor` after any gap > N days
        # (Tết closure, a stretch of failed runs, backfill-then-enable-later), because
        # the window slides forward daily while the store never grows.
        window_from = date.fromordinal(today.toordinal() - max(1, history_days))
        anchor_floor = date.fromordinal(max(stored).toordinal() - 3)
        window = _fetch_records(spec, date_from=min(window_from, anchor_floor),
                                date_to=today, fetch=fetch)
        fetched: dict[date, float] = {
            r.observation_date: float(r.value)
            for r in window
            if r.observation_date is not None and r.value
        }
        if not fetched:
            item["status"] = "error"
            item["warnings"].append("window fetch yielded no usable bars")
            continue

        # Anchors: most recent stored dates the source also serves (today excluded —
        # an intraday bar may still be forming and is not evidence of a restatement).
        overlap = sorted(d for d in stored if d in fetched and d != today)
        anchors = overlap[-max(1, cfg.anchor_days):]
        item["anchors_checked"] = len(anchors)
        if not anchors:
            # The window reaches the stored tail by construction, so an empty overlap
            # means the source no longer serves our stored dates (delisting / dead
            # ticker) — fail closed AND surface it (counts into ok:false ⇒ exit 1).
            item["status"] = "no_anchor"
            item["warnings"].append("source no longer serves any stored date — cannot verify basis")
            continue

        mismatched = [
            d for d in anchors
            if stored[d] <= 0 or abs(fetched[d] / stored[d] - 1.0) * 100.0 > cfg.epsilon_pct
        ]
        item["mismatched_anchors"] = len(mismatched)

        if mismatched:
            # RESTATED: refetch the whole history and insert it as one new revision.
            new_rev = latest_rev + 1
            deep = _fetch_records(spec, date_from=deep_from, date_to=today, fetch=fetch)
            # Point-in-time: a corporate-action restatement only became KNOWABLE on the
            # reconcile day. Stamp release_date=today (still satisfying
            # release_date >= observation_date) so as-of backtests before today keep
            # the prior revision; live latest-revision reads still see the new basis.
            deep = [
                replace(
                    r,
                    revision=new_rev,
                    source_record_id=f"{r.source_record_id}@r{new_rev}",
                    release_date=max(today, r.observation_date or today),
                )
                for r in deep
            ]
            payloads, invalid = _payloads(session, resolver, deep)
            # Coverage = share of the STORED DATES the reload reproduces (never a raw
            # row count: a capped/paginated response that adds pre-history but drops
            # the recent tail must not become the canonical series — that would
            # truncate history AND strand future runs in permanent `no_anchor`).
            payload_dates = {p["price_date"] for p in payloads}
            coverage = len(payload_dates & set(stored)) / max(1, len(stored))
            if invalid or coverage < cfg.min_reload_coverage:
                # A partial reload would BECOME the canonical series (single-basis
                # read rule) and silently truncate history — refuse instead.
                item["status"] = "error"
                item["warnings"].append(
                    f"reload rejected: invalid={invalid}, stored-date coverage={coverage:.2f} "
                    f"< min {cfg.min_reload_coverage} of {len(stored)} stored dates"
                )
                continue
            worst = _max_abs_return_pct([(p["price_date"], float(p["value"])) for p in payloads])
            if worst > cfg.jump_alert_pct:
                item["warnings"].append(f"abnormal jump in reloaded series: {worst:.1f}% day-over-day")
            item["revision"] = new_rev
            item["rows"] = len(payloads)
            if dry_run:
                item["status"] = "would_restate"
                continue
            try:
                _atomic_insert(session, FactFamily.price_daily, payloads)
            except SQLAlchemyError as exc:  # rolled back — nothing persisted
                item["status"] = "error"
                item["warnings"].append(f"atomic reload failed: {type(exc).__name__}")
                continue
            item["status"] = "restated"
            continue

        # Basis verified — plain append of genuinely new dates at the SAME revision.
        new_dates = sorted(d for d in fetched if d not in stored)
        if not new_dates:
            item["status"] = "fresh"
            continue
        recs = [
            # revision ≥ 1 appends also get the revision-qualified provenance id so a
            # rev-N row never shares source_record_id with a rev-0 row of the same date
            replace(r, revision=latest_rev, source_record_id=f"{r.source_record_id}@r{latest_rev}")
            if latest_rev
            else r
            for r in window
            if r.observation_date in set(new_dates)
        ]
        payloads, invalid = _payloads(session, resolver, recs)
        if invalid:
            item["warnings"].append(f"{invalid} window record(s) failed validation and were skipped")
        last_stored = max(stored)
        worst = _max_abs_return_pct(
            [(last_stored, stored[last_stored])] + [(p["price_date"], float(p["value"])) for p in payloads]
        )
        if worst > cfg.jump_alert_pct:
            item["warnings"].append(f"abnormal jump at append boundary: {worst:.1f}% day-over-day")
        item["revision"] = latest_rev
        item["rows"] = len(payloads)
        if dry_run:
            item["status"] = "would_append"
            continue
        try:
            _atomic_insert(session, FactFamily.price_daily, payloads)
        except SQLAlchemyError as exc:
            item["status"] = "error"
            item["warnings"].append(f"atomic append failed: {type(exc).__name__}")
            continue
        item["status"] = "appended"

    statuses: list[str] = [str(i.get("status")) for i in items]
    return {
        "mode": "dry_run" if dry_run else "write",
        "instruments": items,
        "totals": {s: statuses.count(s) for s in sorted(set(statuses))},
        # no_anchor is a stall that would otherwise repeat silently forever — both it
        # and error must turn the run red (the cron step is continue-on-error anyway).
        "ok": not any(s in ("error", "no_anchor") for s in statuses),
    }
