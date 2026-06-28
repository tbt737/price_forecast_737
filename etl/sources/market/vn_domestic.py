"""Vietnam domestic spot-price connector (feeds ``fact_price_daily``).

Config-driven (``configs/ingestion/sources.yaml`` -> ``vn_prices``): each endpoint
declares a parser FORMAT (not a commodity name) — a PNJ JSON feed or a Phú Quý HTML
partial — plus the URL, the product key to pick, and the currency. Adding a VN price =
adding a config row, never editing this engine.

These domestic sources publish only the CURRENT day's price, so each run yields one
record per instrument, dated ``today``. The fetch function is injectable so tests
never touch the network; per-endpoint failures are fail-soft (skip, don't crash).
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import VnPriceSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource

#: fetch(url) -> raw response body (text)
VnFetch = Callable[[str], str]


def _http_fetch(url: str) -> str:
    import urllib.request

    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - fixed https price endpoints
        return resp.read().decode("utf-8", errors="replace")


def _to_float(token: str) -> float | None:
    """Parse a VN-formatted number ('2,314,000' / '14850') to float; None if not numeric."""
    cleaned = token.strip().replace(",", "").replace(".", "")
    if not cleaned.isdigit():
        return None
    return float(cleaned)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip().upper()


def parse_pnj_json(raw: str, product_key: str) -> float | None:
    """PNJ edge-api: ``{"data":[{"masp":..,"giaban":..,"giamua":..}]}``. Return the
    sell price (``giaban``) of the product whose ``masp`` equals ``product_key``."""
    data = json.loads(raw)
    key = product_key.strip().upper()
    for item in data.get("data", []) or []:
        if str(item.get("masp", "")).strip().upper() == key:
            v = item.get("giaban")
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None
    return None


_TR = re.compile(r"<tr\b.*?</tr>", re.I | re.S)
_TD = re.compile(r"<td\b.*?</td>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def parse_phuquy_silver_html(raw: str, product_key: str) -> float | None:
    """Phú Quý silver partial: rows of
    ``<td>name</td><td>unit</td><td>buy</td><td>sell</td>``. Return the SELL price
    (GIÁ BÁN RA, the last numeric cell) of the row whose product name contains
    ``product_key``. Rows with a non-numeric sell (e.g. '_') yield None."""
    key = _norm(product_key)
    for tr in _TR.findall(raw):
        cells = [_norm(_TAG.sub(" ", td)) for td in _TD.findall(tr)]
        if not cells:
            continue
        name = cells[0]
        if key not in name:
            continue
        numbers = [_to_float(c) for c in cells[1:]]
        numbers = [n for n in numbers if n is not None and n > 0]
        return numbers[-1] if numbers else None  # GIÁ BÁN RA is the last numeric column
    return None


#: parser FORMAT name -> implementation. Keyed on format, never on commodity.
PARSERS: dict[str, Callable[[str, str], float | None]] = {
    "pnj_json": parse_pnj_json,
    "phuquy_silver_html": parse_phuquy_silver_html,
}


class VnDomesticPriceSource(BaseSource):
    family = FactFamily.price_daily

    def __init__(self, specs: list[VnPriceSpec], *, today: date | None = None, fetch: VnFetch | None = None) -> None:
        self._specs = specs
        self._today = today or date.today()
        self._fetch = fetch or _http_fetch
        self.source_code = specs[0].source_code if specs else "vn_domestic"

    def collect(self) -> Iterable[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        for spec in self._specs:
            parser = PARSERS.get(spec.parser)
            if parser is None:  # unknown format in config — skip cleanly, don't crash
                continue
            try:
                price = parser(self._fetch(spec.url), spec.product_key)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                price = None  # network/parse failure is fail-soft per endpoint
            if price is None or price <= 0:
                continue
            obs = self._today
            payload = {
                "commodity_code": spec.commodity_code,
                "instrument_code": spec.instrument_code,
                "data_source_code": spec.source_code,
                "url": spec.url,
                "product_key": spec.product_key,
                "observation_date": obs.isoformat(),
                "value": price,
                "currency": spec.currency,
            }
            record = NormalizedRecord(
                family=FactFamily.price_daily,
                data_source_code=spec.source_code,
                commodity_code=spec.commodity_code,
                instrument_code=spec.instrument_code,
                observation_date=obs,
                release_date=obs + timedelta(days=spec.release_lag_days),
                value=price,
                currency=spec.currency,
            )
            records.append(
                attach_provenance(
                    record, payload, source_code=spec.source_code,
                    origin=f"{spec.url}#{spec.product_key}", key=obs.isoformat(),
                )
            )
        return records
