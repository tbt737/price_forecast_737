"""Ingestion orchestrator + CLI.

Builds the configured connectors, runs each through the fail-closed connector
provenance gate, then writes the accepted records via the transaction-safe,
idempotent ``write_batch``. Default is DRY-RUN (no writes); pass ``--write`` to
persist. Re-running is safe — provenance/grain make replays idempotent.

Usage (reads DATABASE_URL from .env):
    python -m etl.ingest --dry-run            # plan only (default)
    python -m etl.ingest --write              # persist
    python -m etl.ingest --write --sources prices --period 1mo
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# The ETL write path imports the ORM models from the FastAPI app package; make it
# importable when this module is run standalone (python -m etl.ingest).
_API_DIR = Path(__file__).resolve().parent.parent / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy.orm import Session  # noqa: E402

from etl.ingestion.config import IngestionConfig, load_ingestion_config  # noqa: E402
from etl.sources.base import BaseSource  # noqa: E402
from etl.sources.events.noaa_oni import NoaaOniSource  # noqa: E402
from etl.sources.macro.yahoo_fx import MacroFxSource  # noqa: E402
from etl.sources.market.vn_domestic import VnAppMobGoldSource, VnDomesticPriceSource  # noqa: E402
from etl.sources.market.vn_stocks import VnStockHistorySource  # noqa: E402
from etl.sources.market.yahoo import YahooPriceSource  # noqa: E402
from etl.sources.supply_demand.usda_psd_bulk import UsdaPsdBulkSource  # noqa: E402
from etl.sources.weather.nasa_power import NasaPowerSource  # noqa: E402
from etl.writer import write_batch  # noqa: E402


def build_connectors(
    config: IngestionConfig, *, which: str, period: str, weather_days: int, today: date, history_days: int = 400
) -> list[BaseSource]:
    connectors: list[BaseSource] = []
    if which in ("prices", "all") and config.prices:
        connectors.append(YahooPriceSource(config.prices, period=period))
    if which in ("vn_prices", "all") and config.vn_prices:
        connectors.append(VnDomesticPriceSource(config.vn_prices, today=today))
    # Historical VN source runs ONLY when explicitly requested (never in the daily "all"
    # run — it would refetch months of history every day).
    if which == "vn_history" and config.vn_history:
        import calendar

        ts_to = calendar.timegm(today.timetuple())
        ts_from = ts_to - max(1, history_days) * 86400
        connectors.append(VnAppMobGoldSource(config.vn_history, date_from=ts_from, date_to=ts_to))
    # Listed-equity daily bars: same explicit-only, date-range pattern as vn_history
    # (the daily workflow tops up a short window; a deep backfill widens --history-days).
    if which == "vn_stocks" and config.vn_stocks:
        import calendar

        ts_to = calendar.timegm(today.timetuple())
        ts_from = ts_to - max(1, history_days) * 86400
        connectors.append(VnStockHistorySource(config.vn_stocks, date_from=ts_from, date_to=ts_to))
    if which in ("weather", "all") and config.weather:
        end = today - timedelta(days=1)
        start = end - timedelta(days=weather_days)
        connectors.append(NasaPowerSource(config.weather, start=start, end=end))
    if which in ("macro", "all") and config.macro:
        connectors.append(MacroFxSource(config.macro, period=period))
    if which in ("events", "all") and config.events:
        connectors.append(NoaaOniSource(config.events))
    if which in ("supply_demand", "all") and config.supply_demand:
        connectors.append(UsdaPsdBulkSource(config.supply_demand))
    return connectors


def run(
    session: Session,
    *,
    which: str = "all",
    dry_run: bool = True,
    period: str = "5d",
    weather_days: int = 10,
    today: date | None = None,
    history_days: int = 400,
) -> dict[str, Any]:
    config = load_ingestion_config()
    connectors = build_connectors(
        config, which=which, period=period, weather_days=weather_days,
        today=today or date.today(), history_days=history_days,
    )

    accepted = []
    rejected = 0
    by_connector = []
    for connector in connectors:
        report = connector.gate()  # collect + fail-closed provenance gate
        accepted.extend(report.accepted)
        rejected += len(report.rejected)
        by_connector.append(
            {"connector": type(connector).__name__, "accepted": len(report.accepted), "rejected": len(report.rejected)}
        )

    write = write_batch(session, accepted, dry_run=dry_run)
    return {
        "mode": "dry_run" if dry_run else "write",
        "connectors": by_connector,
        "gated_accepted": len(accepted),
        "gated_rejected": rejected,
        "write": write.to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest real source data into the platform DB.")
    parser.add_argument("--write", action="store_true", help="persist (default is dry-run)")
    parser.add_argument(
        "--backfill", action="store_true", help="bulk historical backfill (fast ON CONFLICT DO NOTHING path)"
    )
    parser.add_argument(
        "--reconcile", action="store_true",
        help="restatement-aware reconcile for --sources vn_stocks (anchor check, append at "
             "latest revision, atomic revision-bump reload on restatement); dry-run unless --write",
    )
    parser.add_argument(
        "--csv-import", dest="csv_import", help="run a named import from configs/ingestion/csv_imports.yaml"
    )
    parser.add_argument(
        "--sources",
        choices=[
            "prices", "vn_prices", "vn_history", "vn_stocks",
            "weather", "macro", "events", "supply_demand", "all",
        ],
        default="all",
    )
    parser.add_argument("--period", default="5d", help="yfinance history period (e.g. 5d, 1mo, 1y, 10y, max)")
    parser.add_argument("--weather-days", type=int, default=10, help="weather lookback window (days)")
    parser.add_argument(
        "--history-days", dest="history_days", type=int, default=400,
        help="vn_history / vn_stocks lookback window (days)",
    )
    args = parser.parse_args()

    from app.db.session import get_session_factory

    from db.seeds.seed_ingestion_sources import seed_ingestion_sources

    session = get_session_factory()()
    try:
        seed_ingestion_sources(session)
        session.commit()
        if args.reconcile:
            if args.sources != "vn_stocks":
                parser.error("--reconcile currently applies to --sources vn_stocks only")
            if args.backfill:
                parser.error("--reconcile and --backfill are mutually exclusive")
            from datetime import date as _date

            from etl.restatement import reconcile_stock_history

            cfg = load_ingestion_config()
            result = reconcile_stock_history(
                session, cfg.vn_stocks, today=_date.today(), config=cfg.vn_stocks_reconcile,
                history_days=args.history_days, dry_run=not args.write,
            )
        elif args.csv_import:
            from etl.backfill import backfill
            from etl.ingestion.config import load_csv_imports
            from etl.sources.csv_file import CsvPriceSource

            spec = load_csv_imports()[args.csv_import]
            result = backfill(session, connectors=[CsvPriceSource(spec)])
        elif args.backfill:
            from etl.backfill import backfill

            result = backfill(
                session, which=args.sources, period=args.period,
                weather_days=args.weather_days, history_days=args.history_days,
            )
        else:
            result = run(
                session,
                which=args.sources,
                dry_run=not args.write,
                period=args.period,
                weather_days=args.weather_days,
                history_days=args.history_days,
            )
    finally:
        session.close()

    import json

    print(json.dumps(result, indent=2, default=str))
    return _exit_code(result)


def _exit_code(result: dict[str, Any]) -> int:
    """Non-zero when a WRITE was attempted but the batch did NOT commit — so CI/cron can
    detect the silent-failure case (an all-or-nothing rollback) instead of a green exit 0.
    Dry-runs and idempotent backfills (0 new rows is fine) exit 0. A reconcile report
    with any per-instrument ``error`` (fail-closed skip) is also non-zero."""
    if isinstance(result, dict) and result.get("ok") is False and "instruments" in result:
        return 1
    write = result.get("write") if isinstance(result, dict) else None
    if isinstance(write, dict) and write.get("mode") == "write" and write.get("committed") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
