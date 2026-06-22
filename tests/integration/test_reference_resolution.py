"""Integration: the reference resolver maps codes -> keys and rejects unknown codes."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from etl.contracts import FactFamily, NormalizedRecord
from etl.resolution import ReferenceResolver
from etl.validation import ErrorCode


def _rec(**kw) -> NormalizedRecord:
    base = dict(family=FactFamily.macro_daily, data_source_code="manual", release_date=date(2025, 1, 10))
    base.update(kw)
    return NormalizedRecord(**base)


def test_resolves_valid_codes(seeded_session: Session) -> None:
    resolver = ReferenceResolver(seeded_session)
    rec = NormalizedRecord(
        family=FactFamily.price_daily,
        data_source_code="manual",
        release_date=date(2025, 1, 10),
        commodity_code="ALPHA",
        region_code="REG1",
        instrument_code="INST1",
    )
    res = resolver.resolve(rec)
    assert res.ok
    assert res.commodity_key is not None
    assert res.region_key is not None
    assert res.market_instrument_key is not None
    assert res.data_source_key is not None


def test_rejects_unknown_commodity(seeded_session: Session) -> None:
    res = ReferenceResolver(seeded_session).resolve(_rec(commodity_code="NOPE"))
    assert not res.ok and ErrorCode.UNKNOWN_COMMODITY in res.error_codes


def test_rejects_unknown_region(seeded_session: Session) -> None:
    res = ReferenceResolver(seeded_session).resolve(_rec(region_code="NOPE"))
    assert not res.ok and ErrorCode.UNKNOWN_REGION in res.error_codes


def test_rejects_unknown_instrument(seeded_session: Session) -> None:
    res = ReferenceResolver(seeded_session).resolve(_rec(commodity_code="ALPHA", instrument_code="NOPE"))
    assert not res.ok and ErrorCode.UNKNOWN_INSTRUMENT in res.error_codes


def test_rejects_unknown_source(seeded_session: Session) -> None:
    res = ReferenceResolver(seeded_session).resolve(_rec(data_source_code="nope_source"))
    assert not res.ok and ErrorCode.UNKNOWN_SOURCE in res.error_codes


def test_instrument_without_known_commodity_is_unknown(seeded_session: Session) -> None:
    res = ReferenceResolver(seeded_session).resolve(_rec(instrument_code="INST1"))  # no commodity_code
    assert not res.ok and ErrorCode.UNKNOWN_INSTRUMENT in res.error_codes
