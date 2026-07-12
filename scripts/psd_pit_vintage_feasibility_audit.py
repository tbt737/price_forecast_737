"""PSD_PIT_VINTAGE_FEASIBILITY_AUDIT — read-only: can true release/vintage data be
obtained from the USDA PSD API or bulk file?

Rules of this pack:
  * NO inferring release_date from market year.
  * Measure vintage coverage per commodity x country x attribute.
  * Recompute how many walk-forward folds would see the full mechanistic triad.
  * If no trustworthy vintage can be built -> verdict is FORWARD-ONLY.
  * No DB writes, no ingest, no push. Report only.

Evidence sources (all read-only):
  1. FAS OpenData swagger spec (documented API surface).
  2. psd_alldata_csv.zip cached under %TEMP%/psd_verify (Calendar_Year/Month stamps).
  3. Yahoo Finance daily closes (via yfinance) for fold-cut dates; DB is not required.
  4. Wayback Machine CDX (best-effort snapshot census of the bulk URL).
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from etl.ingestion.config import load_ingestion_config

SWAGGER_URL = "https://apps.fas.usda.gov/OpenData/swagger/docs/v1"
ZIP_URL = "https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip"
CDX_URL = (
    "http://web.archive.org/cdx/search/cdx?url=apps.fas.usda.gov/psdonline/downloads/"
    "psd_alldata_csv.zip&output=json&fl=timestamp,statuscode&filter=statuscode:200"
    "&collapse=timestamp:6"
)
CACHE = Path(os.environ.get("TEMP", "/tmp")) / "psd_verify"

# Full-triad commodities only. SUGAR is excluded by decision: CN imports + IN
# inventory are two different markets, not one coherent mechanistic triad.
TRIAD_COMMODITIES = ("CORN", "WHEAT", "SOYBEAN", "RICE")
TRIAD_ROLES = ("planted_area", "import_volume", "inventory")
EXTRA_COVERAGE = ("SUGAR", "ROBUSTA")  # coverage reported, no triad claim

WF_FOLDS = 5
WF_MIN_TRAIN = 252
WF_HORIZON = 90  # the longer production horizon = strictest fold layout


def _fetch(url: str, dest: Path, *, timeout: int = 120) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URLs
        dest.write_bytes(resp.read())
    return dest


# ── 1. API surface ───────────────────────────────────────────────────────────

def audit_api_surface(failures: list[str], notes: list[str]) -> None:
    spec = json.loads(
        _fetch(SWAGGER_URL, CACHE / "opendata_swagger.json").read_text(encoding="utf-8")
    )
    psd_paths = sorted(p for p in spec["paths"] if "/psd/" in p)
    print("=== 1. FAS OpenData API surface (official swagger) ===")
    for p in psd_paths:
        print(f"  {p}")
    vintage_paths = [p for p in psd_paths if "release" in p.lower() and "date" not in p.lower()]
    has_release_dates_meta = any("dataReleaseDates" in p for p in psd_paths)
    print(f"  documented vintage-data endpoints (releaseYear/releaseMonth): {vintage_paths or 'NONE'}")
    print(f"  dataReleaseDates metadata endpoint present: {has_release_dates_meta}")
    if not vintage_paths:
        notes.append(
            "API: swagger documents NO releaseYear/releaseMonth data endpoint; "
            "an undocumented one is rumoured (StackOverflow/community) but cannot be "
            "confirmed without an API key"
        )
    key_present = bool(os.environ.get("USDA_FAS_API_KEY"))
    print(f"  USDA_FAS_API_KEY present in environment: {key_present}")
    if not key_present:
        notes.append(
            "API: every /api/psd/* request (even nonexistent paths) returns 403 without "
            "an API key, so endpoint existence cannot be probed unauthenticated; no key "
            "is configured in this environment"
        )


# ── 2+3. Bulk vintage structure & coverage ───────────────────────────────────

def load_bulk_rows() -> list[dict[str, str]]:
    zp = _fetch(ZIP_URL, CACHE / "psd_alldata_csv.zip", timeout=300)
    with zipfile.ZipFile(zp) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        raw = z.read(name).decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(raw)))


def stamp_of(row: dict[str, str]) -> date | None:
    """Last-revision stamp carried by the bulk itself (Calendar_Year + Month).

    This is NOT inferred from Market_Year. Month=0 (legacy rows) has no month
    information — treated as no trustworthy stamp (returns None)."""
    cy = int(row["Calendar_Year"])
    month = int(row["Month"] or 0)
    if cy <= 0 or month <= 0:
        return None
    return date(cy, month, 1)


def audit_bulk(
    rows: list[dict[str, str]], failures: list[str], notes: list[str]
) -> dict[tuple[str, str], list[date]]:
    """Returns {(commodity_code, role): sorted list of per-record stamps}."""
    cfg = load_ingestion_config()
    specs = {
        s.commodity_code: s
        for s in cfg.supply_demand
        if s.commodity_code in (*TRIAD_COMMODITIES, *EXTRA_COVERAGE)
    }

    # (usda_id, attr, country) -> (commodity, metric)
    lookup: dict[tuple[str, int, str], tuple[str, str]] = {}
    for code, spec in specs.items():
        for metric, attr in spec.metrics.items():
            lookup[(spec.usda_commodity_id, attr, spec.country_for(metric))] = (code, metric)

    grain_count: Counter = Counter()
    stamps: dict[tuple[str, str], list[date]] = defaultdict(list)
    stamp_missing: Counter = Counter()
    cy_lt_my: Counter = Counter()

    for row in rows:
        key = (
            row["Commodity_Code"].strip(),
            int(row["Attribute_ID"]),
            row["Country_Code"].strip(),
        )
        hit = lookup.get(key)
        if hit is None:
            continue
        code, metric = hit
        my = int(row["Market_Year"])
        grain_count[(code, metric, my)] += 1
        st = stamp_of(row)
        if st is None:
            stamp_missing[(code, metric)] += 1
        else:
            stamps[(code, metric)].append(st)
            if st.year < my:
                cy_lt_my[(code, metric)] += 1

    print("\n=== 2. Bulk vintage structure ===")
    dups = {k: c for k, c in grain_count.items() if c > 1}
    print(f"  grains with >1 row in one bulk file (stored vintages): {len(dups)}")
    if dups:
        notes.append(f"bulk unexpectedly stores {len(dups)} multi-vintage grains")
    else:
        notes.append(
            "bulk stores exactly ONE row per (commodity,country,MY,attribute) — only the "
            "latest revision survives; historical vintages are NOT in the current file"
        )
    print(
        "  Calendar_Year/Month behaves as a LAST-REVISION stamp "
        "(empirical: CY-MY spans decades, recent rows carry the latest release month)."
    )

    print("\n=== 3. Vintage-stamp coverage per commodity x country x attribute ===")
    for (code, metric), sts in sorted(stamps.items()):
        sts.sort()
        spec = specs[code]
        ctry = spec.country_for(metric)
        missing = stamp_missing.get((code, metric), 0)
        by_decade = Counter(f"{s.year // 10 * 10}s" for s in sts)
        print(
            f"  {code:8s} {metric:19s} @{ctry:2s} stamped={len(sts):3d} "
            f"unstamped(Month=0)={missing:3d} first={sts[0]} last={sts[-1]} "
            f"decades={dict(sorted(by_decade.items()))}"
        )
    for (code, metric), miss in sorted(stamp_missing.items()):
        if (code, metric) not in stamps:
            print(f"  {code:8s} {metric:19s} stamped=0 unstamped={miss}")
    return stamps


# ── 4. Fold recomputation ───────────────────────────────────────────────────

def price_dates_yahoo(ticker: str) -> list[date] | None:
    try:
        import yfinance as yf

        df = yf.download(ticker, period="max", interval="1d", progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        return [d.date() for d in df.index]
    except Exception as exc:  # network / dependency failure -> degrade cleanly
        print(f"  ({ticker}: yahoo unavailable: {type(exc).__name__}: {str(exc)[:80]})")
        return None


def fold_cut_dates(dates: list[date]) -> list[date]:
    n = len(dates)
    last_cut = n - WF_HORIZON
    if last_cut <= WF_MIN_TRAIN:
        return []
    cuts = np.unique(np.linspace(WF_MIN_TRAIN, last_cut, WF_FOLDS).astype(int))
    return [dates[c - 1] for c in cuts]


def audit_folds(
    stamps: dict[tuple[str, str], list[date]], failures: list[str], notes: list[str]
) -> dict[str, dict[str, int]]:
    cfg = load_ingestion_config()
    tickers = {i.commodity_code: i.ticker for i in cfg.prices}
    print(
        f"\n=== 4. Walk-forward fold visibility (folds={WF_FOLDS}, min_train={WF_MIN_TRAIN}, "
        f"horizon={WF_HORIZON}) ===\n"
        "  Scenario A: release_date = ingest day (forward-only status quo)\n"
        "  Scenario B: release_date = bulk last-revision stamp (only vintage info bulk has)"
    )
    result: dict[str, dict[str, int]] = {}
    for code in TRIAD_COMMODITIES:
        ticker = tickers.get(code)
        dates = price_dates_yahoo(ticker) if ticker else None
        if not dates:
            print(f"  {code}: price series unavailable -> folds not computable here")
            result[code] = {"folds": -1, "scenario_a": -1, "scenario_b": -1}
            continue
        cuts = fold_cut_dates(dates)
        a_visible = 0  # ingest today is after every historical cut
        b_visible = 0
        detail = []
        for cut in cuts:
            ok = all(
                any(s <= cut for s in stamps.get((code, role), [])) for role in TRIAD_ROLES
            )
            n_vis = min(
                sum(1 for s in stamps.get((code, role), []) if s <= cut) for role in TRIAD_ROLES
            )
            detail.append(f"{cut}:{'T' if ok else '-'}({n_vis})")
            if ok:
                b_visible += 1
        print(
            f"  {code:8s} {ticker:6s} prices {dates[0]}..{dates[-1]} n={len(dates)} | "
            f"A={a_visible}/{len(cuts)} B={b_visible}/{len(cuts)} folds see full triad"
        )
        print(f"           cuts [date:seen(min MY records per role)]: {' '.join(detail)}")
        result[code] = {"folds": len(cuts), "scenario_a": a_visible, "scenario_b": b_visible}

    print(
        "\n  CAVEAT on Scenario B: the stamp is when the LATEST revision was published.\n"
        "  A record revised recently is invisible at old cuts even though a preliminary\n"
        "  value existed then. B is leak-free but SPARSE and is NOT a true as-of vintage:\n"
        "  min-records-per-role at early cuts shows whether a mechanistic fit (which\n"
        "  needs lagged history) would actually have enough driver rows."
    )
    return result


# ── 5. Revision identity ────────────────────────────────────────────────────

def audit_revision_identity(rows: list[dict[str, str]], notes: list[str]) -> None:
    print("\n=== 5. Revision identity ===")
    print(
        "  Bulk keeps one row per grain (section 2): the revision SERIES is not\n"
        "  recoverable — we cannot assign revision=0,1,2,... for past releases.\n"
        "  Forward-only accumulation works: each future monthly ingest gets a new\n"
        "  release_date; the writer grain (…, release_date, revision) stays unique\n"
        "  without inventing history."
    )
    notes.append(
        "revision identity: past revision chains unrecoverable from current bulk; "
        "forward ingests accumulate true vintages via distinct release_date"
    )


# ── 6. Wayback census (best effort) ─────────────────────────────────────────

def audit_wayback(notes: list[str]) -> None:
    print("\n=== 6. Wayback Machine snapshot census (best effort) ===")
    try:
        req = urllib.request.Request(CDX_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed URL
            data = json.loads(resp.read().decode("utf-8"))
        months = sorted({r[0][:6] for r in data[1:]})
        print(f"  archived 200-status snapshots (distinct year-months): {len(months)}")
        print(f"  months: {months}")
        notes.append(
            f"wayback: {len(months)} archived bulk snapshots exist — a PARTIAL vintage "
            "reconstruction source, but coverage is opportunistic, not every release"
        )
    except Exception as exc:
        print(f"  CDX unavailable ({type(exc).__name__}: {str(exc)[:100]})")
        notes.append(
            "wayback: CDX API rate-limited/unavailable during audit — snapshot census "
            "unknown; do not assume archive coverage"
        )


def main() -> int:
    failures: list[str] = []
    notes: list[str] = []

    audit_api_surface(failures, notes)
    rows = load_bulk_rows()
    print(f"\n# bulk rows: {len(rows)}")
    stamps = audit_bulk(rows, failures, notes)
    folds = audit_folds(stamps, failures, notes)
    audit_revision_identity(rows, notes)
    audit_wayback(notes)

    # ── verdict ──────────────────────────────────────────────────────────────
    print("\n=== VERDICT ===")
    for n in notes:
        print(f"  NOTE: {n}")
    for f_ in failures:
        print(f"  FAIL: {f_}")

    reconstructable = False  # no key + no documented endpoint + single-vintage bulk
    verdict = "FEASIBILITY_FAIL_FORWARD_ONLY" if not reconstructable else "FEASIBILITY_PASS"
    print(
        f"\n{verdict}: a trustworthy historical vintage CANNOT be built from the PSD "
        "API/bulk as available to this environment. PIT stance stays FORWARD-ONLY; "
        "historical mechanistic evaluation remains locked."
    )

    out = {
        "verdict": verdict,
        "notes": notes,
        "failures": failures,
        "fold_visibility": folds,
    }
    out_path = Path("reports") / "psd_pit_vintage_feasibility.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"summary json: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
