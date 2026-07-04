"""ECON-1A research runner — walk-forward backtest of the Van der Pol candidate.

OFFLINE and DB-FREE: builds national-median daily series straight from the local
``data/Agriculture_price_dataset.csv`` (the same Agmarknet source the platform imports),
then runs the research pool (naive / ridge_ar / gbm / gbm_cyc / ou / **vdp**) via the
existing walk-forward harness. Cyclical Indian produce is the intended VdP test bed
(per the regime evidence: model value concentrates in cyclical produce). Futures
(GOLD/CORN/…) live only in the DB and are intentionally out of this offline scope.

Prints an evidence table; writes nothing. Run: ``python scripts/econ1a_vdp_backtest.py``.
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ml.backtests.research_pool import evaluate_commodity  # noqa: E402

CSV_PATH = _REPO / "data" / "Agriculture_price_dataset.csv"
DATE_FMT = "%m/%d/%Y"
TARGETS = ["Onion", "Potato", "Wheat", "Tomato", "Rice"]  # cyclical produce present in the CSV


def load_series(commodity: str) -> tuple[list[date], np.ndarray]:
    """National-median daily Modal_Price series for one commodity (median across all
    markets/varieties per day) — deterministic, causal-orderable."""
    by_date: dict[date, list[float]] = defaultdict(list)
    with CSV_PATH.open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if row.get("Commodity", "").strip().lower() != commodity.lower():
                continue
            try:
                v = float(row["Modal_Price"])
                d = datetime.strptime(row["Price Date"].strip(), DATE_FMT).date()
            except (ValueError, KeyError):
                continue
            if v > 0:
                by_date[d].append(v)
    dates = sorted(by_date)
    values = np.array([statistics.median(by_date[d]) for d in dates], dtype=float)
    return dates, values


def _fmt(x: float) -> str:
    return f"{x:6.2f}" if np.isfinite(x) else "   nan"


def main() -> int:
    horizon = 30
    print(f"ECON-1A Van der Pol backtest — horizon={horizon}, folds=5, source={CSV_PATH.name}\n")
    header = (
        f"{'commodity':10} {'n':>5} {'fold':>4} | "
        f"{'naive':>6} {'ridge':>6} {'gbm':>6} {'gbmcyc':>6} {'ou':>6} {'vdp':>6} | "
        f"{'best':>10} {'+ou':>10} {'+vdp':>10}"
    )
    print(header)
    print("-" * len(header))
    vdp_beats_naive = vdp_beats_pool = catastrophic = evaluated = 0
    for name in TARGETS:
        dates, values = load_series(name)
        if len(values) < 220:
            print(f"{name:10} {len(values):>5}  (skip — insufficient history)")
            continue
        r = evaluate_commodity(dates, values, horizon=horizon, folds=5, min_train=180)
        c = r["candidates"]
        pool_mape = r["best_of_plus_ou"]["mape"]          # current production pool
        pv = r["pool_plus_vdp"]                            # pool + vdp
        evaluated += 1
        if np.isfinite(r["vdp_mape"]) and np.isfinite(r["naive_mape"]) and r["vdp_mape"] < r["naive_mape"]:
            vdp_beats_naive += 1
        if np.isfinite(pv["mape"]) and pv["mape"] < pool_mape - 1e-9:
            vdp_beats_pool += 1
        if np.isfinite(r["vdp_mape"]) and np.isfinite(r["naive_mape"]) and r["vdp_mape"] > 2.0 * r["naive_mape"]:
            catastrophic += 1
        print(
            f"{name:10} {len(values):>5} {r['folds']:>4} | "
            f"{_fmt(r['naive_mape'])} {_fmt(c.get('ridge_ar', float('nan')))} {_fmt(c.get('gbm', float('nan')))} "
            f"{_fmt(c.get('gbm_cyc', float('nan')))} {_fmt(r['ou_mape'])} {_fmt(r['vdp_mape'])} | "
            f"{r['best_of']['choice']:>10} {r['best_of_plus_ou']['choice']:>10} {pv['choice']:>10}"
        )
    print("-" * len(header))
    print(f"\nSUMMARY over {evaluated} commodities (horizon {horizon}):")
    print(f"  vdp beats naive:        {vdp_beats_naive}/{evaluated}")
    print(f"  pool+vdp beats pool:    {vdp_beats_pool}/{evaluated}  (promotion signal — must be a real, repeated edge)")
    print(f"  catastrophic (vdp>2x naive): {catastrophic}/{evaluated}")
    print("\nColumns 'best/+ou/+vdp' = the best-of CHOICE (production 2% margin gate). If '+vdp'")
    print("never chooses 'vdp', the candidate adds nothing under the existing gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
