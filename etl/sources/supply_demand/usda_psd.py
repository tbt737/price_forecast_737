"""USDA FAS PSD *API* connector — DISABLED fail-closed.

Superseded by ``etl.sources.supply_demand.usda_psd_bulk.UsdaPsdBulkSource``, which is
the only PSD path wired into ``build_connectors`` and enforces the hardened contract:
exactly one configured country per metric, country written into the record region and
``source_record_id``, unit taken from the source (never hardcoded), duplicate-grain
detection, and ``release_date`` = real ingest time (forward-only vintage accumulation).

This API path cannot satisfy that contract today (PIT vintage feasibility audit,
commit ``5c78d4d``): the endpoint it used is absent from the official OpenData swagger,
its response carries no country dimension, and no API key is configured to verify a
hardened rewrite. Until a dedicated pack re-enables it against the country-specific
documented endpoint, constructing this source raises immediately so no ingest path can
silently produce PSD records that lack a country.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import SupplyDemandSpec
from etl.sources.base import BaseSource

#: kept for import compatibility with the pre-hardening signature
UsdaFetch = Callable[[str], list[dict[str, Any]]]

_DISABLED_MESSAGE = (
    "UsdaPsdSource (PSD API path) is DISABLED fail-closed: it predates the "
    "country-grain hardened contract (no country filter, no country in provenance, "
    "hardcoded unit) and cannot be verified without an API key. Use UsdaPsdBulkSource. "
    "Re-enabling requires a dedicated approved pack."
)


class UsdaPsdSource(BaseSource):
    family = FactFamily.supply_demand_periodic
    source_code = "USDA_FAS"

    def __init__(self, specs: list[SupplyDemandSpec], *, fetch: UsdaFetch | None = None) -> None:
        raise RuntimeError(_DISABLED_MESSAGE)

    def collect(self) -> Iterable[NormalizedRecord]:  # pragma: no cover - unreachable
        raise RuntimeError(_DISABLED_MESSAGE)
