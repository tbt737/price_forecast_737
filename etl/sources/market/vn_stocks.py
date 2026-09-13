"""Vietnamese listed-equity daily-bar connector (feeds ``fact_price_daily``).

Config-driven (``configs/ingestion/sources.yaml`` -> ``vn_stocks``): each endpoint
declares a ticker plus a parser FORMAT (TradingView-style ``t``/``c`` arrays from a
public chart API) and a URL template — adding a listed equity = adding a config row,
never editing this engine. Quotes are published in thousands of VND; the configured
``scale`` rescales them to full VND at ingest (config-over-code, no hardcoded unit).

Date-range source like the other historical VN feeds: it runs ONLY when explicitly
requested (``--sources vn_stocks``) — the daily workflow tops up a short window, a
deep backfill passes a wide ``--history-days``. The fetch function is injectable so
tests never touch the network; empty bars and transient ``OSError``/timeout are
retried (``FETCH_ATTEMPTS``) then fail-soft per endpoint (skip, don't crash).
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from etl.contracts import FactFamily, NormalizedRecord
from etl.ingestion.config import VnStockSpec
from etl.provenance import attach_provenance
from etl.sources.base import BaseSource

#: fetch(url) -> raw response body (text)
StockFetch = Callable[[str], str]
#: sleep(seconds) — injectable so retry backoff is deterministic in tests
SleepFn = Callable[[float], None]

#: Total tries of the same URL (1 initial + 2 retries) for empty bars / OSError.
FETCH_ATTEMPTS = 3
#: Backoff after attempts 1 and 2 (length must be FETCH_ATTEMPTS - 1).
FETCH_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (0.4, 0.8)


def _http_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https chart endpoints
        return resp.read().decode("utf-8", errors="replace")


def _noop_sleep(_seconds: float) -> None:
    return None


def _fetch_chart_rows(
    url: str,
    *,
    fetch: StockFetch,
    parser: Callable[[str, float], list[dict[str, Any]]],
    scale: float,
    sleep: SleepFn,
) -> list[dict[str, Any]]:
    """Fetch+parse ``url``, retrying empty bars and transient ``OSError``/timeout.

    Same URL, up to ``FETCH_ATTEMPTS`` tries. Empty parsed bars and ``OSError``
    (timeouts included) back off with ``FETCH_RETRY_BACKOFF_SECONDS`` then retry.
    Parse errors (``JSONDecodeError``, ``ValueError``) are not retried — they
    propagate to the caller for the existing fail-soft skip.
    """
    rows: list[dict[str, Any]] = []
    for attempt in range(FETCH_ATTEMPTS):
        try:
            rows = parser(fetch(url), scale)
        except OSError:
            rows = []
        if rows:
            return rows
        if attempt + 1 < FETCH_ATTEMPTS:
            sleep(FETCH_RETRY_BACKOFF_SECONDS[attempt])
    return []


def parse_chart_arrays(raw: str, scale: float) -> list[dict[str, Any]]:
    """TradingView-style daily history: ``{"t": [unix, ...], "c": [close, ...]}``
    (``o``/``h``/``l``/``v`` are ignored). Returns one ``{date, close}`` per bar with
    ``close × scale`` applied; bars with a missing/non-positive close or an invalid
    timestamp are skipped. An arrayless JSON body yields ``[]`` and a non-JSON body
    raises (``collect()`` fails soft per endpoint) — never fabricates a date.
    Timestamps are bucketed as UTC calendar dates (deterministic; the exchange's
    daily bars stamp within the local trading day)."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        return []
    times, closes = data.get("t"), data.get("c")
    if not isinstance(times, list) or not isinstance(closes, list):
        return []
    out: list[dict[str, Any]] = []
    for ts, close in zip(times, closes, strict=False):
        try:
            d = datetime.fromtimestamp(int(ts), UTC).date()
            # Round to the stored precision (fact_price_daily.value is Numeric(20,6)),
            # as the Yahoo connector does. 16.10 * 1000 is 16100.000000000002 in binary
            # float; Postgres stores 16100.000000, and the writer's Decimal(str(...))
            # compare would then read a replay of the SAME bar as a `conflict` — which
            # blocks and rolls back the whole batch. ~1.6% of HOSE ticks hit this.
            value = round(float(close) * scale, 6)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        # json.loads accepts bare NaN/Infinity — both pass `<= 0`, so gate on finiteness too
        if not math.isfinite(value) or value <= 0:
            continue
        out.append({"date": d, "close": value})
    return out


#: parser FORMAT name -> implementation. Keyed on format, never on a ticker.
STOCK_HISTORY_PARSERS: dict[str, Callable[[str, float], list[dict[str, Any]]]] = {
    "chart_arrays_json": parse_chart_arrays,
}


class VnStockHistorySource(BaseSource):
    """Daily-close history for Vietnamese listed equities over a [from, to] window.
    Yields one ``price_daily`` record per source-observed trading date. Empty parsed
    bars and transient ``OSError``/timeout retry the same URL up to ``FETCH_ATTEMPTS``
    times; remaining per-endpoint failures are fail-soft (skip, never crash the run).
    Duplicate dates within one response are dropped deterministically (first wins)."""

    family = FactFamily.price_daily

    def __init__(
        self,
        specs: list[VnStockSpec],
        *,
        date_from: int,
        date_to: int,
        fetch: StockFetch | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self._specs = specs
        self._from = int(date_from)
        self._to = int(date_to)
        self._fetch = fetch or _http_fetch
        # Injected fetch ⇒ no wall-clock wait (offline tests). Production uses time.sleep
        # unless a sleep injectable is provided explicitly.
        if sleep is not None:
            self._sleep = sleep
        elif fetch is not None:
            self._sleep = _noop_sleep
        else:
            self._sleep = time.sleep
        self.source_code = specs[0].source_code if specs else "vn_stocks"

    def collect(self) -> Iterable[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        for spec in self._specs:
            parser = STOCK_HISTORY_PARSERS.get(spec.parser)
            if parser is None:  # unknown format in config — skip cleanly, don't crash
                continue
            try:
                # inside the try: a malformed url_template (bad placeholder) must skip
                # this endpoint like any other per-endpoint failure, not crash the run
                url = spec.url_template.format(ts_from=self._from, ts_to=self._to, ticker=spec.ticker)
                rows = _fetch_chart_rows(
                    url, fetch=self._fetch, parser=parser, scale=spec.scale, sleep=self._sleep
                )
            except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError):
                continue  # network/template/parse failure is fail-soft per endpoint
            origin_base = spec.url_template.split("?", 1)[0]
            seen: set[date] = set()
            for row in rows:
                obs: date = row["date"]
                if obs in seen:
                    continue
                seen.add(obs)
                payload = {
                    "commodity_code": spec.commodity_code,
                    "instrument_code": spec.instrument_code,
                    "data_source_code": spec.source_code,
                    "ticker": spec.ticker,
                    "observation_date": obs.isoformat(),
                    "value": row["close"],
                    "scale": spec.scale,
                    "currency": spec.currency,
                }
                record = NormalizedRecord(
                    family=FactFamily.price_daily,
                    data_source_code=spec.source_code,
                    commodity_code=spec.commodity_code,
                    instrument_code=spec.instrument_code,
                    observation_date=obs,
                    release_date=obs + timedelta(days=spec.release_lag_days),
                    value=row["close"],
                    currency=spec.currency,
                    attributes={"ticker": spec.ticker},
                )
                records.append(
                    attach_provenance(
                        record, payload, source_code=spec.source_code,
                        origin=f"{origin_base}#{spec.ticker}", key=obs.isoformat(),
                    )
                )
        return records
