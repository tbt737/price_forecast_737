"""Offline tests for the Vietnam domestic price connector (GOLD_VN / SILVER_VN).

No network: parsers run against captured real fixtures + tiny synthetic snippets
(for exact-value pinning), and the connector uses an injected fetch.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from etl.contracts import FactFamily
from etl.ingestion.config import VnPriceSpec
from etl.sources.market.vn_domestic import (
    VnDomesticPriceSource,
    parse_phuquy_silver_html,
    parse_pnj_json,
)

_FIX = Path(__file__).resolve().parents[2] / "etl" / "tests" / "fixtures" / "vn"
PNJ_JSON = (_FIX / "pnj_gold.json").read_text(encoding="utf-8")
PHUQUY_HTML = (_FIX / "phuquy_silver.html").read_text(encoding="utf-8")

GOLD_URL = "https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price"
SILVER_URL = "https://giabac.phuquygroup.vn/PhuQuyPrice/SilverPricePartial"
TODAY = date(2026, 6, 29)


# ── parser: PNJ gold JSON ────────────────────────────────────────────────────
def test_pnj_json_exact_value_synthetic() -> None:
    raw = '{"data":[{"masp":"SJC","tensp":"Vàng miếng SJC","giaban":14850,"giamua":14550}]}'
    assert parse_pnj_json(raw, "SJC") == 14850.0
    assert parse_pnj_json(raw, "sjc") == 14850.0  # case-insensitive masp
    assert parse_pnj_json(raw, "N24K") is None  # absent product


def test_pnj_json_real_fixture() -> None:
    for key in ("SJC", "N24K"):
        v = parse_pnj_json(PNJ_JSON, key)
        assert v is not None and v > 0


# ── parser: Phú Quý silver HTML ──────────────────────────────────────────────
def test_phuquy_html_picks_sell_column_synthetic() -> None:
    raw = (
        "<tr><td class='col-product'>BẠC MIẾNG PH&#218; QU&#221; 999 1 LƯỢNG</td>"
        "<td>Vnđ/Lượng</td><td>2,245,000</td><td>2,314,000</td></tr>"
    )
    # GIÁ BÁN RA (sell) is the last numeric cell, NOT the buy price
    assert parse_phuquy_silver_html(raw, "BẠC MIẾNG PHÚ QUÝ 999 1 LƯỢNG") == 2314000.0


def test_phuquy_html_real_fixture_and_edge_cases() -> None:
    assert parse_phuquy_silver_html(PHUQUY_HTML, "BẠC MIẾNG PHÚ QUÝ 999 1 LƯỢNG") == 2314000.0
    # the "BẠC 999 (MIẾNG...)" row has a non-numeric '_' sell → no usable price
    assert parse_phuquy_silver_html(PHUQUY_HTML, "BẠC 999 (MIẾNG - THANH - THỎI)") is None
    assert parse_phuquy_silver_html(PHUQUY_HTML, "KHÔNG TỒN TẠI") is None


# ── connector: collect() with injected fetch ─────────────────────────────────
def _specs() -> list[VnPriceSpec]:
    return [
        VnPriceSpec("GOLD_VN", "PNJ_SJC", "PNJ", "pnj_json", GOLD_URL, "SJC", "VND", 0),
        VnPriceSpec("GOLD_VN", "PNJ_NHAN9999", "PNJ", "pnj_json", GOLD_URL, "N24K", "VND", 0),
        VnPriceSpec("SILVER_VN", "PQ_BAC_MIENG999", "PHU_QUY", "phuquy_silver_html", SILVER_URL, "BẠC MIẾNG PHÚ QUÝ 999 1 LƯỢNG", "VND", 0),
    ]


def _fetch(url: str) -> str:
    return PNJ_JSON if url == GOLD_URL else PHUQUY_HTML


def test_collect_yields_one_record_per_instrument() -> None:
    recs = list(VnDomesticPriceSource(_specs(), today=TODAY, fetch=_fetch).collect())
    assert len(recs) == 3
    by_inst = {r.instrument_code: r for r in recs}
    assert set(by_inst) == {"PNJ_SJC", "PNJ_NHAN9999", "PQ_BAC_MIENG999"}
    silver = by_inst["PQ_BAC_MIENG999"]
    assert silver.commodity_code == "SILVER_VN"
    assert silver.family == FactFamily.price_daily
    assert silver.currency == "VND"
    assert silver.value == 2314000.0
    assert silver.observation_date == TODAY
    assert silver.release_date == TODAY + timedelta(days=0)
    assert silver.data_source_code == "PHU_QUY"
    for r in recs:  # every recorded price is positive
        assert r.value > 0


def test_collect_is_fail_soft_on_fetch_error() -> None:
    def boom(url: str) -> str:
        raise OSError("network down")

    recs = list(VnDomesticPriceSource(_specs(), today=TODAY, fetch=boom).collect())
    assert recs == []  # no crash, no records


def test_collect_skips_unknown_parser_format() -> None:
    bad = [VnPriceSpec("X_VN", "X", "PNJ", "no_such_format", GOLD_URL, "SJC", "VND", 0)]
    assert list(VnDomesticPriceSource(bad, today=TODAY, fetch=_fetch).collect()) == []
