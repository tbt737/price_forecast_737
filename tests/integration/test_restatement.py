"""Offline tests for the restatement-aware reconcile (etl/restatement.py).

Simulates the real failure mode of an ADJUSTED price feed: a corporate action
(15% stock dividend) restates the source's ENTIRE history downward, while the
platform store is append-only. No network: the source is a dict the test mutates,
served through an injected fetch. SQLite in-memory; dims seeded via the real
profile loader; the initial load uses the real bulk-backfill path.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from typing import Any

import pytest
from app.db.base import Base
from app.models import FactPriceDaily
from app.services.profile_loader import LoadSummary, load_profile
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from etl.backfill import backfill
from etl.ingestion.config import StockReconcileConfig, VnStockSpec, load_ingestion_config
from etl.restatement import reconcile_stock_history
from etl.sources.market.vn_stocks import VnStockHistorySource
from ml.forecast import load_price_series

URL_TEMPLATE = "https://chart.example/ohlcs/stock?from={ts_from}&to={ts_to}&symbol={ticker}&resolution=1D"
TODAY = date(2026, 7, 10)

#: ~3 weeks of business days ending the day before TODAY — "basis A" (pre-dividend).
DATES = [d for d in (date(2026, 6, 15) + timedelta(days=i) for i in range(24)) if d.weekday() < 5]
BASIS_A = {d: 100.0 + i for i, d in enumerate(DATES)}  # 100, 101, … per business day


def _spec() -> VnStockSpec:
    return VnStockSpec(
        commodity_code="TSTA_VN", instrument_code="HOSE_TSTA", source_code="ENTRADE",
        parser="chart_arrays_json", url_template=URL_TEMPLATE, ticker="TSTA",
        currency="VND", scale=1.0, release_lag_days=0,
    )


def _profile() -> dict[str, Any]:
    return {
        "commodity_code": "TSTA_VN",
        "commodity_name": "Test equity A",
        "commodity_group": "equity",
        "base_unit": "share",
        "default_currency": "VND",
        "market_instruments": [
            {"instrument_code": "HOSE_TSTA", "exchange": "HOSE", "symbol": "TSTA",
             "contract_unit": "share", "currency": "VND"}
        ],
        "data_sources": [{"source_code": "ENTRADE", "name": "chart API", "access": "public"}],
    }


def _fetch_for(source_state: dict[date, float]):
    """Injected fetch: serves the CURRENT source basis, windowed by the url's from/to."""

    def fetch(url: str) -> str:
        qs = dict(p.split("=") for p in url.split("?", 1)[1].split("&"))
        lo, hi = int(qs["from"]), int(qs["to"])
        bars = sorted(
            (calendar.timegm(d.timetuple()) + 3 * 3600, v)  # 03:00 UTC == 10:00 ICT
            for d, v in source_state.items()
        )
        window = [(t, v) for t, v in bars if lo <= t <= hi]
        return json.dumps({"t": [t for t, _ in window], "c": [v for _, v in window]})

    return fetch


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    load_profile(s, _profile(), LoadSummary())
    s.commit()
    yield s
    s.close()
    engine.dispose()


def _seed_initial(session: Session, source_state: dict[date, float]) -> None:
    """Initial deep load through the REAL bulk-backfill path (prod sequence step 8)."""
    src = VnStockHistorySource(
        [_spec()], date_from=0, date_to=calendar.timegm(TODAY.timetuple()) + 86_000,
        fetch=_fetch_for(source_state),
    )
    result = backfill(session, connectors=[src])
    assert result["inserted_total"] == len(source_state)


def _series(session: Session) -> dict[date, float]:
    """The canonical series exactly as the ML read path sees it (single basis)."""
    out = load_price_series(session, "TSTA_VN")
    assert out is not None
    return dict(zip(out["dates"], out["values"], strict=True))


def _all_rows(session: Session) -> list[tuple[date, float, int]]:
    return [
        (r.price_date, float(r.value), int(r.revision))
        for r in session.execute(select(FactPriceDaily).order_by(FactPriceDaily.price_date)).scalars()
    ]


# ── fail-closed defaults ─────────────────────────────────────────────────────
def test_empty_store_writes_nothing(session: Session) -> None:
    report = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=_fetch_for(BASIS_A), dry_run=False
    )
    assert report["instruments"][0]["status"] == "empty" and report["ok"]
    assert session.execute(select(func.count()).select_from(FactPriceDaily)).scalar_one() == 0


def test_no_anchor_overlap_writes_nothing(session: Session) -> None:
    _seed_initial(session, BASIS_A)
    # Source only serves dates far in the future — nothing overlaps the store.
    future_only = {TODAY + timedelta(days=30): 500.0}
    report = reconcile_stock_history(
        session, [_spec()], today=TODAY + timedelta(days=31),
        fetch=_fetch_for(future_only), history_days=2, dry_run=False,
    )
    assert report["instruments"][0]["status"] == "no_anchor"
    assert len(_all_rows(session)) == len(BASIS_A)  # untouched


def test_dry_run_never_writes(session: Session) -> None:
    _seed_initial(session, BASIS_A)
    restated = {d: round(v * 0.85, 4) for d, v in BASIS_A.items()}
    report = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=_fetch_for(restated), dry_run=True
    )
    assert report["mode"] == "dry_run"
    assert report["instruments"][0]["status"] == "would_restate"
    assert {r[2] for r in _all_rows(session)} == {0}  # still only revision 0


# ── append path (anchors match) ──────────────────────────────────────────────
def test_append_new_dates_then_idempotent(session: Session) -> None:
    _seed_initial(session, BASIS_A)
    grown = dict(BASIS_A)
    d_new = TODAY - timedelta(days=1)  # a fresh business day on the SAME basis
    assert d_new.weekday() < 5 and d_new not in grown
    grown[d_new] = 124.5

    report = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=_fetch_for(grown), dry_run=False
    )
    item = report["instruments"][0]
    assert item["status"] == "appended" and item["revision"] == 0 and item["rows"] == 1
    assert _series(session)[d_new] == 124.5

    # Re-running the SAME payload is a no-op ("fresh"), byte-identical store.
    before = _all_rows(session)
    report2 = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=_fetch_for(grown), dry_run=False
    )
    assert report2["instruments"][0]["status"] == "fresh"
    assert _all_rows(session) == before


def test_append_jump_only_warns(session: Session) -> None:
    _seed_initial(session, BASIS_A)
    grown = dict(BASIS_A)
    grown[TODAY - timedelta(days=1)] = max(BASIS_A.values()) * 1.5  # +50% boundary jump
    report = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=_fetch_for(grown), dry_run=False
    )
    item = report["instruments"][0]
    assert item["status"] == "appended"  # written — the alert is a warning, not a block
    assert any("abnormal jump" in w for w in item["warnings"])


# ── restatement path (the dividend scenario) ─────────────────────────────────
def test_restatement_reloads_full_series_atomically(session: Session) -> None:
    _seed_initial(session, BASIS_A)
    # 15% stock dividend: the source restates the WHOLE history downward and keeps
    # publishing new days on the new basis.
    restated = {d: round(v * 0.85, 4) for d, v in BASIS_A.items()}
    d_new = TODAY - timedelta(days=1)
    restated[d_new] = round(105.9 * 0.85, 4)

    report = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=_fetch_for(restated), dry_run=False
    )
    item = report["instruments"][0]
    assert item["status"] == "restated" and item["revision"] == 1
    assert item["rows"] == len(restated)

    # Old basis is preserved for audit (revision 0), new basis is complete (revision 1).
    rows = _all_rows(session)
    assert [r for r in rows if r[2] == 0] and [r for r in rows if r[2] == 1]
    rev0 = {d: v for d, v, rev in rows if rev == 0}
    rev1 = {d: v for d, v, rev in rows if rev == 1}
    assert rev0 == BASIS_A  # never UPDATEd
    assert rev1 == pytest.approx(restated)

    # Single-basis rule: the ML read path serves ONLY the new basis — no mixing.
    served = _series(session)
    assert served == pytest.approx(restated)
    assert all(abs(v / BASIS_A[d] - 1.0) > 0.1 for d, v in served.items() if d in BASIS_A)

    # PIT: restated rows became knowable on the reconcile day, not on the historical
    # observation dates — so as-of views before TODAY keep the prior revision.
    rev1_release = {
        r.release_date
        for r in session.execute(select(FactPriceDaily).where(FactPriceDaily.revision == 1)).scalars()
    }
    assert rev1_release == {TODAY}


def test_restated_store_converges_and_is_idempotent(session: Session) -> None:
    _seed_initial(session, BASIS_A)
    restated = {d: round(v * 0.85, 4) for d, v in BASIS_A.items()}
    r1 = reconcile_stock_history(session, [_spec()], today=TODAY, fetch=_fetch_for(restated), dry_run=False)
    assert r1["instruments"][0]["status"] == "restated"
    before = _all_rows(session)

    # Second run against the SAME source state: anchors now match revision 1 ⇒ no new
    # revision, no new rows — the store has converged.
    r2 = reconcile_stock_history(session, [_spec()], today=TODAY, fetch=_fetch_for(restated), dry_run=False)
    assert r2["instruments"][0]["status"] == "fresh"
    assert _all_rows(session) == before

    # A SECOND corporate action bumps to revision 2 — monotonic, never reused.
    restated2 = {d: round(v * 0.5, 4) for d, v in restated.items()}  # 2:1 split
    r3 = reconcile_stock_history(session, [_spec()], today=TODAY, fetch=_fetch_for(restated2), dry_run=False)
    assert r3["instruments"][0]["status"] == "restated" and r3["instruments"][0]["revision"] == 2
    assert _series(session) == pytest.approx(restated2)


def test_truncated_reload_is_refused(session: Session) -> None:
    _seed_initial(session, BASIS_A)
    # Restated AND truncated: the source only serves the last 3 days on the new basis.
    tail = dict(sorted(BASIS_A.items())[-3:])
    truncated = {d: round(v * 0.85, 4) for d, v in tail.items()}
    report = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=_fetch_for(truncated), dry_run=False
    )
    item = report["instruments"][0]
    assert item["status"] == "error" and not report["ok"]
    assert any("coverage" in w for w in item["warnings"])
    # Fail-closed: nothing was written; the canonical series is still basis A.
    assert {r[2] for r in _all_rows(session)} == {0}
    assert _series(session) == pytest.approx(BASIS_A)


def test_duplicate_grain_inside_reload_aborts_whole_instrument(session: Session) -> None:
    _seed_initial(session, BASIS_A)
    restated = {d: round(v * 0.85, 4) for d, v in BASIS_A.items()}

    dup_dates: list[date] = []

    def duplicating_fetch(url: str) -> str:
        raw = _fetch_for(restated)(url)
        body = json.loads(raw)
        if len(body["t"]) > 5:  # the deep fetch — inject a duplicate timestamp+close pair
            body["t"].append(body["t"][0])
            body["c"].append(body["c"][0] + 1.0)  # same date, different value
            dup_dates.append(date.fromtimestamp(body["t"][0]))
        return json.dumps(body)

    report = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=duplicating_fetch, dry_run=False
    )
    item = report["instruments"][0]
    # The connector dedups repeated dates deterministically (first wins), so the reload
    # stays clean — this pins that a poisoned response cannot fabricate duplicate grain.
    assert item["status"] == "restated"
    rev1_dates = [d for d, _v, rev in _all_rows(session) if rev == 1]
    assert len(rev1_dates) == len(set(rev1_dates))  # no duplicate (date, revision)


def test_capped_response_with_extra_prehistory_is_refused(session: Session) -> None:
    # Reviewer PoC: a deep response that ADDS plenty of pre-history but is MISSING the
    # recent stored tail must be refused — raw row counts would score it > 1.0 and the
    # truncated series would become canonical, stranding future runs in `no_anchor`.
    _seed_initial(session, BASIS_A)
    kept = dict(sorted(BASIS_A.items())[:2])  # only the 2 oldest stored dates survive
    capped = {d: round(v * 0.85, 4) for d, v in kept.items()}
    cursor = date(2026, 4, 1)
    while len(capped) <= len(BASIS_A):
        if cursor.weekday() < 5 and cursor not in BASIS_A:
            capped[cursor] = 80.0 + len(capped)
        cursor += timedelta(days=1)
    assert len(capped) > len(BASIS_A)

    # Short window must still return RECENT stored dates (mismatched) so restatement
    # is detected; only the deep reload is the capped/truncated payload.
    restated_window = {d: round(v * 0.85, 4) for d, v in BASIS_A.items()}

    def dual_fetch(url: str) -> str:
        qs = dict(p.split("=") for p in url.split("?", 1)[1].split("&"))
        lo, hi = int(qs["from"]), int(qs["to"])
        source = capped if (hi - lo) > 40 * 86400 else restated_window
        return _fetch_for(source)(url)

    report = reconcile_stock_history(
        session, [_spec()], today=TODAY, fetch=dual_fetch, dry_run=False
    )
    item = report["instruments"][0]
    assert item["status"] == "error" and any("coverage" in w for w in item["warnings"])
    assert {r[2] for r in _all_rows(session)} == {0}  # canonical series untouched
    assert _series(session) == pytest.approx(BASIS_A)


def test_append_after_restatement_lands_at_new_revision(session: Session) -> None:
    # After a reload to revision 1, daily appends must land at revision 1 too — an
    # append at revision 0 would be INVISIBLE to the single-basis read paths.
    _seed_initial(session, BASIS_A)
    restated = {d: round(v * 0.85, 4) for d, v in BASIS_A.items()}
    r1 = reconcile_stock_history(session, [_spec()], today=TODAY, fetch=_fetch_for(restated), dry_run=False)
    assert r1["instruments"][0]["status"] == "restated"

    grown = dict(restated)
    d_new = TODAY - timedelta(days=1)
    grown[d_new] = 90.5
    r2 = reconcile_stock_history(session, [_spec()], today=TODAY, fetch=_fetch_for(grown), dry_run=False)
    item = r2["instruments"][0]
    assert item["status"] == "appended" and item["revision"] == 1
    assert _series(session)[d_new] == 90.5  # visible through the canonical read path
    rev_of_new = [rev for d, _v, rev in _all_rows(session) if d == d_new]
    assert rev_of_new == [1]


def test_atomic_insert_duplicate_grain_rolls_back_everything(session: Session) -> None:
    # Direct pin of the all-or-nothing insert: a duplicate grain inside one batch hits
    # the DB unique index, raises, and leaves NOTHING behind (no partial write).
    from sqlalchemy.exc import SQLAlchemyError

    from etl.contracts import FactFamily
    from etl.ingestion.config import StockReconcileConfig as _C  # noqa: F401 (context only)
    from etl.resolution import ReferenceResolver
    from etl.restatement import _atomic_insert, _fetch_records, _payloads

    _seed_initial(session, BASIS_A)
    extra_day = {TODAY + timedelta(days=30): 130.0}
    recs = _fetch_records(
        _spec(), date_from=TODAY, date_to=TODAY + timedelta(days=40), fetch=_fetch_for(extra_day)
    )
    payloads, invalid = _payloads(session, ReferenceResolver(session), recs)
    assert invalid == 0 and len(payloads) == 1
    before = len(_all_rows(session))
    with pytest.raises(SQLAlchemyError):
        _atomic_insert(session, FactFamily.price_daily, [payloads[0], dict(payloads[0])])
    assert len(_all_rows(session)) == before  # rolled back — the valid twin is gone too


# ── config plumbing ──────────────────────────────────────────────────────────
def test_reconcile_config_loads_from_sources_yaml() -> None:
    cfg = load_ingestion_config()
    rc = cfg.vn_stocks_reconcile
    assert isinstance(rc, StockReconcileConfig)
    assert rc.epsilon_pct == 0.5 and rc.anchor_days == 5
    assert rc.jump_alert_pct == 15.0 and rc.min_reload_coverage == 0.9
    assert rc.deep_from == "2000-01-01"
