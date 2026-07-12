"""PSD-LIQUID-DRY-RUN-AUDIT — read-only audit of USDA PSD bulk vs commit 0152103 config.

Scope: CORN / WHEAT / SOYBEAN / RICE (triad) + SUGAR (imports/inventory only).
Checks per commodity x country x attribute x market year:
  coverage, min/max period, cardinality, unit consistency, duplicate grain,
  missing rate, country semantics (no cross-country merge), connector grain
  collision simulation, and PIT impact of release_date = ingest date.

NO DB writes. Reads the cached bulk zip under %TEMP%/psd_verify (downloads once
if absent). Exit 0 = report produced (PASS/FAIL verdict is in the report body).
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

from etl.ingestion.config import load_ingestion_config
from etl.provenance import gate_records
from etl.sources.supply_demand.usda_psd_bulk import UsdaPsdBulkSource

ZIP_URL = "https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip"
CACHE = Path(os.environ.get("TEMP", "/tmp")) / "psd_verify" / "psd_alldata_csv.zip"

AUDIT_COMMODITIES = ("CORN", "WHEAT", "SOYBEAN", "RICE", "SUGAR")
# Walk-forward parameters used by production (ml/forecast.py contract).
WF_FOLDS = 5
WF_MIN_TRAIN = 252


def _ensure_zip() -> Path:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE.exists() and CACHE.stat().st_size > 1_000_000:
        return CACHE
    req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 - fixed https URL
        CACHE.write_bytes(resp.read())
    return CACHE


def _load_rows() -> list[dict[str, str]]:
    with zipfile.ZipFile(_ensure_zip()) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        raw = z.read(name).decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(raw)))


def main() -> int:
    cfg = load_ingestion_config()
    specs = {s.commodity_code: s for s in cfg.supply_demand if s.commodity_code in AUDIT_COMMODITIES}
    missing = set(AUDIT_COMMODITIES) - set(specs)
    if missing:
        print(f"FAIL: configured series missing for {sorted(missing)}")
        return 2

    # attr lookup: usda_commodity_id -> {attribute_id: metric_code}
    attr_lookup: dict[str, dict[int, str]] = {}
    unit_expected: dict[tuple[str, str], str | None] = {}
    for code, spec in specs.items():
        attr_lookup[spec.usda_commodity_id] = {v: k for k, v in spec.metrics.items()}
        for d in spec.metric_details:
            unit_expected[(code, d.metric_code)] = d.unit

    rows = _load_rows()
    print(f"# PSD bulk rows total: {len(rows)}")

    # ── per commodity x country x attribute aggregation ──────────────────────
    # key: (commodity_code, country_code, country_name, metric_code)
    agg: dict[tuple[str, str, str, str], dict] = defaultdict(
        lambda: {"n": 0, "npos": 0, "nzero": 0, "years": set(), "units": Counter(), "months": Counter()}
    )
    # in-CSV duplicate grain: (commodity, country, MY, attr) seen more than once
    csv_grain: Counter = Counter()
    # connector grain simulation: what the writer would see with region_key NULL:
    # (commodity_code, metric_code, period_start) — release_date/revision constant per run
    connector_grain: Counter = Counter()
    world_rows: Counter = Counter()
    code_by_usda = {s.usda_commodity_id: c for c, s in specs.items()}

    for row in rows:
        usda_id = row["Commodity_Code"].strip()
        if usda_id not in attr_lookup:
            continue
        aid = int(row["Attribute_ID"])
        metric = attr_lookup[usda_id].get(aid)
        if metric is None:
            continue
        code = code_by_usda[usda_id]
        ctry_code = row["Country_Code"].strip()
        ctry_name = row["Country_Name"].strip()
        my = int(row["Market_Year"])
        month = int(row["Month"] or 0) or 1
        unit = row["Unit_Description"].strip()
        try:
            val = float(row["Value"])
        except ValueError:
            val = float("nan")

        k = (code, ctry_code, ctry_name, metric)
        a = agg[k]
        a["n"] += 1
        a["years"].add(my)
        a["units"][unit] += 1
        a["months"][month] += 1
        if val > 0:
            a["npos"] += 1
        elif val == 0:
            a["nzero"] += 1

        csv_grain[(code, ctry_code, my, metric)] += 1
        connector_grain[(code, metric, date(my, month, 1))] += 1
        if "world" in ctry_name.lower():
            world_rows[(code, metric)] += 1

    failures: list[str] = []
    warnings: list[str] = []

    # ── report: commodity x attribute x country ───────────────────────────────
    print("\n=== Coverage per commodity x attribute x country (top by rows) ===")
    for code in AUDIT_COMMODITIES:
        metrics = sorted({k[3] for k in agg if k[0] == code})
        for metric in metrics:
            entries = [(k, v) for k, v in agg.items() if k[0] == code and k[3] == metric]
            entries.sort(key=lambda kv: -kv[1]["n"])
            n_countries = len(entries)
            total = sum(v["n"] for _, v in entries)
            print(f"\n## {code} / {metric}: countries={n_countries} rows={total}")
            for (_, cc, cn, _), v in entries[:8]:
                yrs = sorted(v["years"])
                span = yrs[-1] - yrs[0] + 1
                miss = span - len(yrs)
                unit_top = v["units"].most_common(1)[0][0]
                print(
                    f"  {cc:4s} {cn[:28]:28s} MY {yrs[0]}-{yrs[-1]} n={v['n']:4d} "
                    f"npos={v['npos']:4d} zero={v['nzero']:4d} missing_years={miss} "
                    f"unit={unit_top!r} my_start_months={dict(v['months'])}"
                )
            if n_countries > 8:
                print(f"  ... and {n_countries - 8} more countries")

            # unit consistency across all countries
            all_units = Counter()
            for _, v in entries:
                all_units.update(v["units"])
            expected = unit_expected.get((code, metric))
            if len(all_units) > 1:
                failures.append(f"{code}/{metric}: mixed units {dict(all_units)}")
            elif expected and next(iter(all_units)) != expected:
                failures.append(
                    f"{code}/{metric}: unit {next(iter(all_units))!r} != config {expected!r}"
                )

            has_world = any("world" in k[2].lower() for k, _ in entries)
            print(f"  world_aggregate_present={has_world}")

    # ── duplicate grain checks ────────────────────────────────────────────────
    csv_dups = {k: c for k, c in csv_grain.items() if c > 1}
    print(f"\n=== In-CSV duplicate (commodity,country,MY,attr): {len(csv_dups)} ===")
    for k, c in list(csv_dups.items())[:10]:
        print(f"  {k} x{c}")
    if csv_dups:
        warnings.append(f"in-CSV duplicate country-grain rows: {len(csv_dups)}")

    # Pre-hardening reference: how many rows WOULD collide if country were ignored.
    collisions = {k: c for k, c in connector_grain.items() if c > 1}
    total_rows = sum(connector_grain.values())
    would_drop = sum(c - 1 for c in collisions.values())
    print(
        f"\n=== Country-collapse reference (if country were ignored) ===\n"
        f"  rows across all countries: {total_rows}; would-collide rows: {would_drop} "
        f"({would_drop / total_rows * 100:.1f}%) — hardened connector must avoid this"
    )

    # ── configured-country verification (fail-closed semantics) ──────────────
    print("\n=== Configured country per series (must exist with data) ===")
    for code, spec in specs.items():
        for metric in spec.metrics:
            ctry = spec.country_for(metric)
            hit = next(
                (v for k, v in agg.items() if k[0] == code and k[1] == ctry and k[3] == metric),
                None,
            )
            if hit is None:
                failures.append(f"{code}/{metric}@{ctry}: configured country has NO rows in bulk")
                print(f"  {code:8s} {metric:14s} @{ctry}: MISSING")
            else:
                yrs = sorted(hit["years"])
                print(
                    f"  {code:8s} {metric:14s} @{ctry} region={spec.region_for(metric)} "
                    f"n={hit['n']} npos={hit['npos']} MY {yrs[0]}-{yrs[-1]}"
                )

    # ── dry-run collect + provenance gate (no DB) ─────────────────────────────
    csv_text_path = CACHE.parent / "psd_alldata.csv"
    if csv_text_path.exists():
        csv_text = csv_text_path.read_text(encoding="utf-8")
    else:
        with zipfile.ZipFile(CACHE) as z:
            name = next(n for n in z.namelist() if n.endswith(".csv"))
            csv_text = z.read(name).decode("utf-8")
    records = list(UsdaPsdBulkSource(list(specs.values()), fetch=lambda: csv_text).collect())
    gated = gate_records(records)
    n_bad = len(gated.rejected)
    dup_ids = Counter(r.source_record_id for r in records)
    dup_id_count = sum(c - 1 for c in dup_ids.values() if c > 1)
    writer_grain = Counter(
        (r.commodity_code, r.region_code, r.metric_code, r.period_start) for r in records
    )
    grain_collisions = sum(c - 1 for c in writer_grain.values() if c > 1)
    regions = Counter(r.region_code for r in records)
    print(
        f"\n=== Dry-run collect + gate (hardened connector) ===\n"
        f"  records={len(records)} gate_rejected={n_bad}\n"
        f"  provenance collisions={dup_id_count}  writer-grain collisions={grain_collisions}\n"
        f"  regions on records: {dict(regions)}"
    )
    if n_bad:
        failures.append(f"provenance gate rejected {n_bad} records")
    if dup_id_count:
        failures.append(f"{dup_id_count} duplicate source_record_ids")
    if grain_collisions:
        failures.append(f"{grain_collisions} writer-grain collisions after hardening")
    if any(r.region_code in (None, "") for r in records):
        failures.append("records missing region_code after hardening")

    # ── PIT impact of release_date = ingest date ─────────────────────────────
    yrs_all = sorted({y for v in agg.values() for y in v["years"]})
    print(
        f"\n=== PIT impact (release_date = ingest date) ===\n"
        f"  PSD market years span {yrs_all[0]}-{yrs_all[-1]}, but EVERY record would get\n"
        f"  release_date = ingest day. Walk-forward (folds={WF_FOLDS}, min_train={WF_MIN_TRAIN})\n"
        f"  places all fold cut dates strictly in the past => folds that can see any\n"
        f"  supply-driver value: 0/{WF_FOLDS} (0%). mechanistic_fourier_supply cannot be\n"
        f"  evaluated on history until either (a) >= {WF_MIN_TRAIN} post-ingest daily rows\n"
        f"  accrue (~1 trading year), or (b) a per-release-month PIT reconstruction pack\n"
        f"  is approved (PSD releaseMonth API preserves historical vintages)."
    )
    warnings.append(f"PIT: 0/{WF_FOLDS} historical folds see drivers with release_date=ingest")

    # ── SUGAR / COCOA guards ─────────────────────────────────────────────────
    sugar_metrics = set(specs["SUGAR"].metrics)
    if sugar_metrics != {"import_volume", "inventory"}:
        failures.append(f"SUGAR metrics {sorted(sugar_metrics)} != imports/inventory only")
    else:
        print("\nSUGAR: imports/inventory only — NOT mechanistic_ready (planted_area absent). OK")
    if any(s.commodity_code == "COCOA" for s in cfg.supply_demand):
        failures.append("COCOA present in supply_demand series")
    else:
        print("COCOA: excluded from config. OK")

    # ── verdict ──────────────────────────────────────────────────────────────
    print("\n=== VERDICT ===")
    for w in warnings:
        print(f"  WARN: {w}")
    for f_ in failures:
        print(f"  FAIL: {f_}")
    verdict = "FAIL" if failures else "PASS"
    print(f"\nAUDIT_{verdict} (read-only; no DB writes performed)")

    out = {
        "verdict": verdict,
        "failures": failures,
        "warnings": warnings,
        "n_records_dry_run": len(records),
        "provenance_collisions": dup_id_count,
        "writer_grain_collisions": grain_collisions,
        "pre_hardening_would_drop": would_drop,
        "pre_hardening_total": total_rows,
    }
    out_path = Path("reports") / "psd_liquid_dry_run_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"summary json: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
