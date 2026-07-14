"""One-shot acquisition of Vietnam retail fuel adjustment-period history (read-only).

Pulls every adjustment period ("kỳ điều hành") exposed by a public fuel-price data
API discovered behind a data page's date widget, and writes RAW files only —
NO database writes, NO connector changes:

- ``data/raw/cafef_gasoline_periods.jsonl`` — one JSON line per period (full item
  list + provenance: source URL, fetch timestamp UTC).
- ``data/raw/cafef_gasoline_periods_wide.csv`` — one row per period, one column per
  product (audit/cross-check artifact; NOT the ingest CSV).

The per-day forward-filled ingest CSV is generated separately AFTER the period table
has been cross-checked against independent sources. Usage:

    python scripts/fetch_cafef_gasoline_history.py
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API = "https://apiweb.cafef.vn/api/v1/Gasoline"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
SLEEP_S = 0.4  # be polite: ~2.5 req/s max against a public API
TIMEOUT_S = 30


def _fetch(date_value: str | None) -> dict:
    qs = f"?date={urllib.parse.quote(date_value)}" if date_value else ""
    req = urllib.request.Request(API + qs, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://cafef.vn/"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https endpoint
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    first = _fetch(None)
    dates = first.get("availableDates") or []
    print(f"available periods: {len(dates)} ({dates[-1]['text']} .. {dates[0]['text']})")

    rows: list[dict] = []
    for i, d in enumerate(dates, 1):
        value = d["value"]
        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            data = _fetch(value)
        except OSError as exc:
            print(f"  FAIL {value}: {exc}")  # fail-soft per period; rerun to fill gaps
            continue
        if data.get("selectedDate") != value:  # server must echo the requested period
            print(f"  MISMATCH {value} -> {data.get('selectedDate')}")
            continue
        rows.append(
            {
                "period_value": value,
                "display_date": data.get("displayDate"),
                "unit": data.get("unit"),
                "updated_text": data.get("updatedText"),
                "items": [
                    {"name": it.get("name"), "price": it.get("price"), "change": it.get("change")}
                    for it in (data.get("items") or [])
                ],
                "source_url": f"{API}?date={urllib.parse.quote(value)}",
                "fetched_at_utc": fetched_at,
            }
        )
        if i % 25 == 0:
            print(f"  fetched {i}/{len(dates)}")
        time.sleep(SLEEP_S)

    def period_key(r: dict) -> datetime:
        return datetime.strptime(r["period_value"], "%d/%m/%Y %H:%M:%S")

    rows.sort(key=period_key)

    jsonl_path = OUT_DIR / "cafef_gasoline_periods.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    products = sorted({it["name"] for r in rows for it in r["items"] if it.get("name")})
    csv_path = OUT_DIR / "cafef_gasoline_periods_wide.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period_value", "display_date", *products, "source_url", "fetched_at_utc"])
        for r in rows:
            by_name = {it["name"]: it["price"] for it in r["items"]}
            w.writerow(
                [r["period_value"], r["display_date"], *[by_name.get(p, "") for p in products],
                 r["source_url"], r["fetched_at_utc"]]
            )

    print(f"wrote {len(rows)} periods -> {jsonl_path}")
    print(f"wrote wide audit table -> {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
