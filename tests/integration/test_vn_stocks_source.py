"""Offline tests for the Vietnamese listed-equity daily-bar connector (vn_stocks).

No network: the parser runs against a captured real fixture + tiny synthetic
snippets (for exact-value pinning), and the connector uses an injected fetch.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from etl.contracts import FactFamily
from etl.ingestion.config import VnStockSpec, load_ingestion_config
from etl.sources.market.vn_stocks import VnStockHistorySource, parse_chart_arrays

_FIX = Path(__file__).resolve().parents[2] / "etl" / "tests" / "fixtures" / "vn"
STOCK_JSON = (_FIX / "entrade_stock_daily.json").read_text(encoding="utf-8")

URL_TEMPLATE = "https://chart.example/ohlcs/stock?from={ts_from}&to={ts_to}&symbol={ticker}&resolution=1D"


def _spec(ticker: str = "FPT", parser: str = "chart_arrays_json", scale: float = 1000.0) -> VnStockSpec:
    return VnStockSpec(
        commodity_code=f"{ticker}_VN", instrument_code=f"HOSE_{ticker}", source_code="ENTRADE",
        parser=parser, url_template=URL_TEMPLATE, ticker=ticker, currency="VND",
        scale=scale, release_lag_days=0,
    )


# ── parser: TradingView-style t/c arrays ─────────────────────────────────────
def test_parse_chart_arrays_exact_value_synthetic() -> None:
    # unix 1746410400 → 2025-05-05 UTC; published quote 91.41 (thousands) → 91410 VND
    raw = '{"t":[1746410400],"o":[91.0],"h":[92.0],"l":[90.5],"c":[91.41],"v":[100]}'
    assert parse_chart_arrays(raw, 1000.0) == [{"date": date(2025, 5, 5), "close": 91410.0}]
    assert parse_chart_arrays(raw, 1.0) == [{"date": date(2025, 5, 5), "close": 91.41}]  # scale is config


def test_parse_chart_arrays_skips_bad_bars() -> None:
    raw = json.dumps({
        "t": [1746410400, "not-a-ts", 1746496800, 1746583200],
        "c": [91.41, 92.0, -1.0, None],
    })
    # bad timestamp, non-positive close and null close are all skipped
    assert parse_chart_arrays(raw, 1000.0) == [{"date": date(2025, 5, 5), "close": 91410.0}]


def test_parse_chart_arrays_rejects_non_finite_closes() -> None:
    # json.loads accepts bare NaN/Infinity — neither may ever reach fact_price_daily
    raw = '{"t":[1746410400,1746496800,1746583200],"c":[NaN,Infinity,91.41]}'
    assert parse_chart_arrays(raw, 1000.0) == [{"date": date(2025, 5, 7), "close": 91410.0}]


def test_parse_chart_arrays_arrayless_bodies_yield_empty() -> None:
    assert parse_chart_arrays("{}", 1000.0) == []
    assert parse_chart_arrays('{"t": 1, "c": 2}', 1000.0) == []  # scalars, not arrays
    assert parse_chart_arrays("[1, 2]", 1000.0) == []  # JSON but not an object
    with pytest.raises(json.JSONDecodeError):  # non-JSON raises; collect() fails soft
        parse_chart_arrays("<html>block page</html>", 1000.0)


def test_parse_chart_arrays_real_fixture() -> None:
    rows = parse_chart_arrays(STOCK_JSON, 1000.0)
    assert len(rows) == 49  # captured window: 2025-05-05 … 2025-07-10
    assert rows[0] == {"date": date(2025, 5, 5), "close": 91410.0}
    assert rows[-1] == {"date": date(2025, 7, 10), "close": 105180.0}
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)


# ── connector: collect() with injected fetch ─────────────────────────────────
def test_collect_maps_records_and_formats_url() -> None:
    seen_urls: list[str] = []

    def fetch(url: str) -> str:
        seen_urls.append(url)
        return STOCK_JSON

    ts_from, ts_to = 1_746_000_000, 1_752_200_000
    recs = list(VnStockHistorySource([_spec()], date_from=ts_from, date_to=ts_to, fetch=fetch).collect())
    assert seen_urls == [f"https://chart.example/ohlcs/stock?from={ts_from}&to={ts_to}&symbol=FPT&resolution=1D"]
    assert len(recs) == 49
    r = recs[0]
    assert r.commodity_code == "FPT_VN" and r.instrument_code == "HOSE_FPT"
    assert r.family == FactFamily.price_daily and r.currency == "VND"
    assert r.data_source_code == "ENTRADE"
    assert r.observation_date == date(2025, 5, 5) and r.value == 91410.0
    assert r.release_date == r.observation_date + timedelta(days=0)  # same-day close
    assert r.attributes["ticker"] == "FPT"
    for rec in recs:
        assert rec.value > 0


def test_collect_dedupes_repeated_dates_first_wins() -> None:
    raw = '{"t":[1746410400,1746410400],"c":[91.41,92.0]}'
    recs = list(VnStockHistorySource([_spec()], date_from=1, date_to=2, fetch=lambda _u: raw).collect())
    assert len(recs) == 1 and recs[0].value == 91410.0


def test_collect_is_fail_soft_per_endpoint() -> None:
    def fetch(url: str) -> str:
        if "symbol=BAD" in url:
            raise OSError("network down")
        return STOCK_JSON

    recs = list(
        VnStockHistorySource([_spec("BAD"), _spec("FPT")], date_from=1, date_to=2, fetch=fetch).collect()
    )
    # the dead ticker is skipped; the healthy one still yields its full window
    assert len(recs) == 49 and {r.instrument_code for r in recs} == {"HOSE_FPT"}


def test_collect_fail_soft_on_malformed_url_template() -> None:
    # A bad placeholder in the (config-supplied) template must skip THAT endpoint only,
    # never crash the run: {symbol} → KeyError, {0} → IndexError inside str.format.
    for bad_template in ("https://chart.example/x?symbol={symbol}", "https://chart.example/x?f={0}"):
        bad = VnStockSpec(
            commodity_code="X_VN", instrument_code="HOSE_X", source_code="ENTRADE",
            parser="chart_arrays_json", url_template=bad_template, ticker="X",
            currency="VND", scale=1000.0, release_lag_days=0,
        )
        recs = list(
            VnStockHistorySource([bad, _spec("FPT")], date_from=1, date_to=2, fetch=lambda _u: STOCK_JSON).collect()
        )
        assert len(recs) == 49 and {r.instrument_code for r in recs} == {"HOSE_FPT"}


def test_vn_stocks_stays_out_of_the_all_run() -> None:
    # Explicit-only source: the daily "all" cron must NEVER build this connector
    # (it would refetch the full window for every ticker every day).
    from datetime import date as _date

    from etl.ingest import build_connectors
    from etl.ingestion.config import IngestionConfig

    cfg = IngestionConfig(
        prices=[], weather=[], macro=[], events=[], supply_demand=[],
        vn_prices=[], vn_history=[], vn_stocks=[_spec()],
    )
    in_all = build_connectors(cfg, which="all", period="5d", weather_days=5, today=_date(2026, 7, 11))
    assert in_all == []
    explicit = build_connectors(cfg, which="vn_stocks", period="5d", weather_days=5, today=_date(2026, 7, 11))
    assert len(explicit) == 1 and isinstance(explicit[0], VnStockHistorySource)


def test_collect_skips_unknown_parser_format_and_non_json() -> None:
    bad_parser = [_spec(parser="no_such_format")]
    assert list(VnStockHistorySource(bad_parser, date_from=1, date_to=2, fetch=lambda _u: STOCK_JSON).collect()) == []
    html = [_spec()]
    assert list(VnStockHistorySource(html, date_from=1, date_to=2, fetch=lambda _u: "<html></html>").collect()) == []


# ── config registry: the vn_stocks section loads into specs ──────────────────
def test_sources_yaml_vn_stocks_section_loads() -> None:
    cfg = load_ingestion_config()
    assert len(cfg.vn_stocks) == 30  # the VN30 basket, one endpoint per constituent
    tickers = {s.ticker for s in cfg.vn_stocks}
    assert len(tickers) == 30  # no duplicate tickers
    for s in cfg.vn_stocks:
        assert s.commodity_code == f"{s.ticker}_VN"
        assert s.instrument_code == f"HOSE_{s.ticker}"
        assert s.parser == "chart_arrays_json" and s.scale == 1000.0
        assert s.currency == "VND" and s.source_code == "ENTRADE"
        assert "{ts_from}" in s.url_template and "{ticker}" in s.url_template
    assert "ENTRADE" in cfg.source_codes
