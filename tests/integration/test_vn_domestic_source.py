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
        VnPriceSpec(
            "SILVER_VN", "PQ_BAC_MIENG999", "PHU_QUY", "phuquy_silver_html", SILVER_URL,
            "BẠC MIẾNG PHÚ QUÝ 999 1 LƯỢNG", "VND", 0,
        ),
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


# ── VNAppMob historical SJC source (VN-PRICE-2A) ─────────────────────────────

from etl.ingestion.config import VnHistorySpec  # noqa: E402
from etl.sources.market.vn_domestic import (  # noqa: E402
    VnAppMobGoldSource,
    _day_chunks,
    parse_vnappmob_gold,
)

VNAPPMOB_JSON = (_FIX / "vnappmob_sjc.json").read_text(encoding="utf-8")
KEY_URL = "https://vapi.vnappmob.com/api/request_api_key?scope=gold"
DATA_URL = "https://vapi.vnappmob.com/api/v2/gold/sjc"
_TOKEN = "eyJSECRET.jwt.TOKEN_must_not_leak"  # sentinel; must never appear in output


def _vnappmob_spec() -> VnHistorySpec:
    return VnHistorySpec("GOLD_VN", "VNAPPMOB_SJC_1L", "VNAPPMOB", "vnappmob_gold",
                         KEY_URL, DATA_URL, "sell_1l", "buy_1l", "VND", 1, 300)


def test_vnappmob_parse_sell_buy_and_date() -> None:
    rows = parse_vnappmob_gold(VNAPPMOB_JSON, "sell_1l", "buy_1l")
    assert len(rows) >= 10
    for r in rows:
        assert isinstance(r["date"], date) and r["sell"] > 0 and (r["buy"] is None or r["buy"] > 0)
    # exact-value pin on a tiny synthetic row (unix 1781143207 → 2026-06-11 UTC)
    syn = '{"results":[{"datetime":"1781143207","sell_1l":"136000000.0","buy_1l":"131000000.0"}]}'
    got = parse_vnappmob_gold(syn, "sell_1l", "buy_1l")
    assert got == [{"date": date(2026, 6, 11), "sell": 136000000.0, "buy": 131000000.0}]


def test_vnappmob_parse_fail_soft_empty_and_malformed() -> None:
    assert parse_vnappmob_gold('{"results":[]}', "sell_1l", "buy_1l") == []
    assert parse_vnappmob_gold('{"results":[{"sell_1l":"1"}]}', "sell_1l", "buy_1l") == []  # no datetime → skip
    assert parse_vnappmob_gold('{"results":[{"datetime":"1781143207","sell_1l":"-5"}]}', "sell_1l", "buy_1l") == []


def test_day_chunks_builds_bounded_windows() -> None:
    lo, hi = 1_000_000, 1_000_000 + 500 * 86400
    chunks = _day_chunks(lo, hi, 300)
    assert len(chunks) == 2 and chunks[0][0] == lo and chunks[-1][1] == hi
    assert all((b - a) <= 300 * 86400 for a, b in chunks)


def test_vnappmob_collect_maps_records_and_uses_key() -> None:
    seen_key = {}

    def fetch(data_url: str, key: str, ts_from: int, ts_to: int) -> str:
        seen_key["key"] = key  # the key IS used as the header arg…
        return VNAPPMOB_JSON

    recs = list(
        VnAppMobGoldSource([_vnappmob_spec()], date_from=1_000_000, date_to=1_000_000 + 30 * 86400,
                           fetch=fetch, mint_key=lambda url: _TOKEN).collect()
    )
    assert len(recs) >= 10
    r = recs[0]
    assert r.commodity_code == "GOLD_VN" and r.instrument_code == "VNAPPMOB_SJC_1L"
    assert r.data_source_code == "VNAPPMOB" and r.currency == "VND" and r.value > 0
    assert r.family == FactFamily.price_daily and isinstance(r.observation_date, date)
    assert seen_key["key"] == _TOKEN  # key was passed to the fetch header


def test_vnappmob_token_never_leaks_into_records() -> None:
    recs = list(
        VnAppMobGoldSource([_vnappmob_spec()], date_from=1_000_000, date_to=1_000_000 + 30 * 86400,
                           fetch=lambda du, k, a, b: VNAPPMOB_JSON, mint_key=lambda url: _TOKEN).collect()
    )
    blob = "".join(str(vars(r)) for r in recs)  # every field of every record
    assert _TOKEN not in blob and "eyJSECRET" not in blob


def test_vnappmob_fail_closed_on_bad_key() -> None:
    def boom_key(url: str) -> str:
        raise OSError("key endpoint down")

    recs = list(VnAppMobGoldSource([_vnappmob_spec()], date_from=1, date_to=2,
                                   fetch=lambda du, k, a, b: VNAPPMOB_JSON, mint_key=boom_key).collect())
    assert recs == []  # no key ⇒ skip, no crash
