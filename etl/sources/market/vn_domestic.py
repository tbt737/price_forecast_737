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
from datetime import UTC, date, datetime, timedelta
from typing import Any

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import VnHistorySpec, VnPriceSpec
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


#: headline "trung bình <N> VNĐ/kg" average on a normalized (upper-cased, tag-stripped) page.
_VN_AVG_VND_KG = re.compile(r"TRUNG BÌNH\s*([\d.,]{5,})\s*VNĐ/KG")


def parse_giatieu_html(raw: str, product_key: str) -> float | None:
    """A Vietnamese domestic spot HTML page that publishes today's headline average plus a
    per-region breakdown, in VNĐ/kg. Tags are stripped and the text upper-cased, then the
    price for ``product_key`` is returned: ``TRUNG_BINH`` (or ``AVG`` / ``AVERAGE``) picks
    the headline average; any other key is matched as a region label (e.g. ``ĐẮK LẮK``) and
    returns the first VN-formatted number after it. Value is the published price as-is;
    None if the key is absent or non-numeric."""
    text = _norm(_TAG.sub(" ", raw))  # unescape + strip tags + collapse whitespace + upper
    key = _norm(product_key)
    if key in ("TRUNG BINH", "TRUNG_BINH", "AVG", "AVERAGE"):
        m = _VN_AVG_VND_KG.search(text)
        return _to_float(m.group(1)) if m else None
    m = re.search(re.escape(key) + r"\s*([\d.,]{5,})", text)  # region label followed by its price
    return _to_float(m.group(1)) if m else None


#: parser FORMAT name -> implementation. Keyed on format, never on commodity.
PARSERS: dict[str, Callable[[str, str], float | None]] = {
    "pnj_json": parse_pnj_json,
    "phuquy_silver_html": parse_phuquy_silver_html,
    "giatieu_html": parse_giatieu_html,
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


# ── VNAppMob historical SJC source (ADDITIVE; does NOT replace the PNJ spot feed) ─────

def parse_vnappmob_gold(raw: str, sell_field: str, buy_field: str) -> list[dict[str, Any]]:
    """The VNAppMob SJC endpoint returns ``{"results": [{"datetime": <unix>,
    "sell_1l": .., "buy_1l": ..}]}``. Return one dict per dated observation
    ``{date, sell, buy}`` (sell = the configured model price). Malformed rows are
    skipped; a non-JSON / resultless body yields ``[]`` — fail closed, never fabricates
    a date. ``datetime`` is bucketed as a UTC calendar date (deterministic)."""
    data = json.loads(raw)
    out: list[dict[str, Any]] = []
    for r in data.get("results") or []:
        try:
            d = datetime.fromtimestamp(int(r["datetime"]), UTC).date()
            sell = float(r[sell_field])
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if sell <= 0:
            continue
        try:
            buy = float(r[buy_field]) if r.get(buy_field) not in (None, "") else None
        except (TypeError, ValueError):
            buy = None
        out.append({"date": d, "sell": sell, "buy": buy})
    return out


#: parser FORMAT name -> implementation for the historical source.
HISTORY_PARSERS: dict[str, Callable[[str, str, str], list[dict[str, Any]]]] = {
    "vnappmob_gold": parse_vnappmob_gold,
}

#: mint_key(key_url) -> token ; fetch(data_url, key, ts_from, ts_to) -> raw json text
VnKeyMint = Callable[[str], str]
VnHistoryFetch = Callable[[str, str, int, int], str]


def _mint_vnappmob_key(key_url: str) -> str:
    """Fetch a fresh free token from the keyless request-key endpoint. The token is used
    ONLY as a request header — never stored, logged, or attached to any record."""
    import urllib.request

    req = urllib.request.Request(key_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - fixed https endpoint
        return str(json.loads(resp.read().decode("utf-8", errors="replace")).get("results") or "")


def _authed_history_fetch(data_url: str, key: str, ts_from: int, ts_to: int) -> str:
    import urllib.request

    url = f"{data_url}?date_from={ts_from}&date_to={ts_to}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https endpoint
        return resp.read().decode("utf-8", errors="replace")


def _day_chunks(ts_from: int, ts_to: int, chunk_days: int) -> list[tuple[int, int]]:
    """Split [ts_from, ts_to] into ≤ chunk_days windows (the API caps very wide ranges)."""
    if ts_to <= ts_from:
        return [(ts_from, ts_to)]
    step = max(1, chunk_days) * 86400
    out, lo = [], ts_from
    while lo < ts_to:
        out.append((lo, min(lo + step, ts_to)))
        lo += step
    return out


class VnAppMobGoldSource(BaseSource):
    """Historical VN domestic SJC bullion source (VNAppMob). Yields one price_daily
    record per source-observed date (value = the configured sell field). Additive — it
    does not touch the PNJ/Phú Quý spot connectors. The API token is minted per run and
    kept out of every record/log. Fails closed (skip) on a bad key or malformed chunk."""

    family = FactFamily.price_daily

    def __init__(
        self,
        specs: list[VnHistorySpec],
        *,
        date_from: int,
        date_to: int,
        fetch: VnHistoryFetch | None = None,
        mint_key: VnKeyMint | None = None,
    ) -> None:
        self._specs = specs
        self._from = int(date_from)
        self._to = int(date_to)
        self._fetch = fetch or _authed_history_fetch
        self._mint = mint_key or _mint_vnappmob_key
        self.source_code = specs[0].source_code if specs else "VNAPPMOB"

    def collect(self) -> Iterable[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        for spec in self._specs:
            parser = HISTORY_PARSERS.get(spec.parser)
            if parser is None:
                continue
            try:
                key = self._mint(spec.key_url)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue  # no key ⇒ skip this source, never crash the run
            if not key:
                continue
            seen: set[date] = set()
            for lo, hi in _day_chunks(self._from, self._to, spec.chunk_days):
                try:
                    rows = parser(self._fetch(spec.data_url, key, lo, hi), spec.field, spec.buy_field)
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    continue  # fail soft per chunk
                for row in rows:
                    obs: date = row["date"]
                    if obs in seen:
                        continue
                    seen.add(obs)
                    payload = {
                        "commodity_code": spec.commodity_code,
                        "instrument_code": spec.instrument_code,
                        "data_source_code": spec.source_code,
                        "observation_date": obs.isoformat(),
                        "value": row["sell"],
                        "buy": row["buy"],
                        "field": spec.field,
                        "currency": spec.currency,
                    }
                    record = NormalizedRecord(
                        family=FactFamily.price_daily,
                        data_source_code=spec.source_code,
                        commodity_code=spec.commodity_code,
                        instrument_code=spec.instrument_code,
                        observation_date=obs,
                        release_date=obs + timedelta(days=spec.release_lag_days),
                        value=row["sell"],
                        currency=spec.currency,
                        attributes={"buy": row["buy"], "field": spec.field},
                    )
                    records.append(
                        attach_provenance(
                            record, payload, source_code=spec.source_code,
                            origin=f"{spec.data_url}#{spec.field}", key=obs.isoformat(),
                        )
                    )
        return records
