"""Derive daily forward-filled diesel CSVs from the adjustment-period table.

Input (source of truth, from fetch_cafef_gasoline_history.py):
    data/raw/cafef_gasoline_periods.jsonl   — one line per kỳ điều hành + provenance

Output (DERIVED artifacts for the csv_imports ingest path; regenerate any time):
    data/vn_diesel_do005s_daily.csv   — Dầu DO 0,05S-II  (one row per calendar day)
    data/vn_diesel_do0001s_daily.csv  — Dầu DO 0,001S-V  (one row per calendar day)

Rules:
- Administered price: step function. Each period's price is forward-filled from its
  EFFECTIVE date through the day before the next period's effective date. If two
  periods share a calendar date, the later one wins that date.
- Two products are written to two files (never merged into one series).
- Each row keeps the originating period + source URL so every daily value is
  traceable back to one kỳ điều hành (provenance survives the derivation).
- Deterministic: same jsonl in, same CSV out (the fill ends at the LAST period's
  effective date, not at the wall clock; the daily connector owns newer dates).
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERIODS = ROOT / "data" / "raw" / "cafef_gasoline_periods.jsonl"

#: product name in the period table -> output csv path
PRODUCTS = {
    "Dầu DO 0,05S-II": ROOT / "data" / "vn_diesel_do005s_daily.csv",
    "Dầu DO 0,001S-V": ROOT / "data" / "vn_diesel_do0001s_daily.csv",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = [json.loads(line) for line in PERIODS.open(encoding="utf-8")]
    rows.sort(key=lambda r: datetime.strptime(r["period_value"], "%d/%m/%Y %H:%M:%S"))

    for product, out_path in PRODUCTS.items():
        periods: list[tuple[datetime, int, str, str]] = []
        for r in rows:
            price = next((it["price"] for it in r["items"] if it["name"] == product), None)
            if price:  # product absent (or 0) in early years — series starts later
                eff = datetime.strptime(r["period_value"], "%d/%m/%Y %H:%M:%S")
                periods.append((eff, int(price), r["period_value"], r["source_url"]))

        daily: dict[date, tuple[int, str, str]] = {}
        for (eff, price, pval, url), nxt in zip(periods, [*periods[1:], None], strict=True):
            end_day = (nxt[0] - timedelta(days=1)).date() if nxt else eff.date()
            day = eff.date()
            # iterating in period order means a same-day later period overwrites
            daily[day] = (price, pval, url)
            while day < end_day:
                day += timedelta(days=1)
                daily[day] = (price, pval, url)

        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "price_vnd", "period_effective", "source_url"])
            for day in sorted(daily):
                price, pval, url = daily[day]
                w.writerow([day.isoformat(), price, pval, url])
        print(f"{product}: {len(periods)} periods -> {len(daily)} daily rows "
              f"({min(daily)} .. {max(daily)}) -> {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
