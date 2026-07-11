"""Single-basis read rule: the price-series endpoint serves ONLY the instrument's
latest revision. A restated (adjusted) history is re-ingested at revision+1 by
etl/restatement.py — mixing revisions would splice two adjustment bases."""

from __future__ import annotations

from datetime import date

from app.models import DimCommodity, DimMarketInstrument, FactPriceDaily
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


def _row(com, inst, d: date, value: float, revision: int) -> FactPriceDaily:
    return FactPriceDaily(
        commodity_key=com.commodity_key, market_instrument_key=inst.market_instrument_key,
        price_date=d, release_date=d, value=value, currency="VND", revision=revision,
    )


def test_prices_endpoint_serves_only_latest_revision(
    client: TestClient, seeded_session: Session
) -> None:
    com = seeded_session.execute(select(DimCommodity).filter_by(commodity_code="FPT_VN")).scalar_one()
    inst = seeded_session.execute(
        select(DimMarketInstrument).filter_by(instrument_code="HOSE_FPT")
    ).scalar_one()
    d1, d2, d3 = date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)
    seeded_session.add_all(
        [
            # revision 0 — pre-dividend basis
            _row(com, inst, d1, 100_000, 0),
            _row(com, inst, d2, 101_000, 0),
            # revision 1 — the restated (post-dividend) basis, incl. a new day
            _row(com, inst, d1, 85_000, 1),
            _row(com, inst, d2, 85_850, 1),
            _row(com, inst, d3, 86_000, 1),
        ]
    )
    seeded_session.commit()

    r = client.get("/commodities/FPT_VN/prices?days=20000")
    assert r.status_code == 200
    body = r.json()
    assert body["instrument_code"] == "HOSE_FPT" and body["currency"] == "VND"
    # ONLY revision-1 values — none of the revision-0 basis leaks into the series.
    assert [p["value"] for p in body["points"]] == [85000.0, 85850.0, 86000.0]
    assert len(body["points"]) == 3  # no duplicate dates from the older revision
