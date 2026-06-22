"""Reference resolver — maps business codes to Phase 2 surrogate keys.

Generic and read-only: it looks up ``dim_*`` rows for the codes on a normalized
record and reports any code that is present but unknown. It NEVER creates missing
dimensions, never inserts, never calls the network, and is not commodity-specific.

Resolution targets (using the real model columns):
    commodity_code     -> dim_commodity.commodity_key
    region_code        -> dim_region.region_key
    instrument_code     -> dim_market_instrument.market_instrument_key   (per-commodity)
    data_source_code   -> dim_data_source.data_source_key
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import DimCommodity, DimDataSource, DimMarketInstrument, DimRegion
from sqlalchemy import select
from sqlalchemy.orm import Session

from etl.contracts import NormalizedRecord
from etl.validation import ErrorCode, ValidationIssue


@dataclass
class ResolutionResult:
    commodity_key: int | None = None
    region_key: int | None = None
    market_instrument_key: int | None = None
    data_source_key: int | None = None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues  # all resolution issues are errors

    @property
    def error_codes(self) -> set[ErrorCode]:
        return {i.code for i in self.issues}

    def resolved_keys(self) -> dict[str, int | None]:
        return {
            "commodity_key": self.commodity_key,
            "region_key": self.region_key,
            "market_instrument_key": self.market_instrument_key,
            "data_source_key": self.data_source_key,
        }


class ReferenceResolver:
    """Resolves business codes to surrogate keys against the live dimensions.

    Caches lookups per instance so a batch resolves each distinct code once.
    Read-only — issues no INSERT/UPDATE/DELETE.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._commodity: dict[str, int | None] = {}
        self._region: dict[str, int | None] = {}
        self._source: dict[str, int | None] = {}
        self._instrument: dict[tuple[int, str], int | None] = {}

    def _commodity_key(self, code: str) -> int | None:
        if code not in self._commodity:
            self._commodity[code] = self._session.execute(
                select(DimCommodity.commodity_key).filter_by(commodity_code=code)
            ).scalar_one_or_none()
        return self._commodity[code]

    def _region_key(self, code: str) -> int | None:
        if code not in self._region:
            self._region[code] = self._session.execute(
                select(DimRegion.region_key).filter_by(region_code=code)
            ).scalar_one_or_none()
        return self._region[code]

    def _source_key(self, code: str) -> int | None:
        if code not in self._source:
            self._source[code] = self._session.execute(
                select(DimDataSource.data_source_key).filter_by(source_code=code)
            ).scalar_one_or_none()
        return self._source[code]

    def _instrument_key(self, commodity_key: int, code: str) -> int | None:
        key = (commodity_key, code)
        if key not in self._instrument:
            self._instrument[key] = self._session.execute(
                select(DimMarketInstrument.market_instrument_key).filter_by(
                    commodity_key=commodity_key, instrument_code=code
                )
            ).scalar_one_or_none()
        return self._instrument[key]

    def resolve(self, record: NormalizedRecord) -> ResolutionResult:
        """Resolve all codes present on the record. Present-but-unknown -> error."""
        result = ResolutionResult()

        if record.commodity_code:
            result.commodity_key = self._commodity_key(record.commodity_code)
            if result.commodity_key is None:
                result.issues.append(
                    ValidationIssue(ErrorCode.UNKNOWN_COMMODITY, f"Unknown commodity_code: {record.commodity_code!r}")
                )

        if record.region_code:
            result.region_key = self._region_key(record.region_code)
            if result.region_key is None:
                result.issues.append(
                    ValidationIssue(ErrorCode.UNKNOWN_REGION, f"Unknown region_code: {record.region_code!r}")
                )

        if record.data_source_code:
            result.data_source_key = self._source_key(record.data_source_code)
            if result.data_source_key is None:
                result.issues.append(
                    ValidationIssue(ErrorCode.UNKNOWN_SOURCE, f"Unknown data_source_code: {record.data_source_code!r}")
                )

        # Instrument is scoped to a commodity, so it can only resolve once the
        # commodity has resolved.
        if record.instrument_code:
            if result.commodity_key is None:
                result.issues.append(
                    ValidationIssue(
                        ErrorCode.UNKNOWN_INSTRUMENT,
                        f"Cannot resolve instrument_code {record.instrument_code!r} without a known commodity",
                    )
                )
            else:
                result.market_instrument_key = self._instrument_key(result.commodity_key, record.instrument_code)
                if result.market_instrument_key is None:
                    result.issues.append(
                        ValidationIssue(
                            ErrorCode.UNKNOWN_INSTRUMENT, f"Unknown instrument_code: {record.instrument_code!r}"
                        )
                    )

        return result
