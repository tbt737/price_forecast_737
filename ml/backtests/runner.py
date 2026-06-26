"""Backtest CLI — thin wrapper around the guarded internal runner (Phase 7A).

Defaults to dry-run with no DB connection. Pass ``--use-db`` to load data from an
injected local/test database session; pass ``--write-registry`` to persist JSON
metadata (never production DB writes).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from ml.runner import ForecastRunner, RunnerConfig  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run guarded walk-forward backtests.")
    parser.add_argument("commodity_code", help="e.g. ROBUSTA, GOLD, CRUDE_OIL")
    parser.add_argument("--model-code", default=None, help="Run a single profile model")
    parser.add_argument("--horizon", default=None, choices=["daily", "weekly", "monthly"])
    parser.add_argument("--min-history", type=int, default=300)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--use-db",
        action="store_true",
        help="Load price data from DATABASE_URL via an injected session (explicit opt-in)",
    )
    parser.add_argument(
        "--write-registry",
        action="store_true",
        help="Persist registry JSON when a model beats naive (implies --no-dry-run)",
    )
    parser.add_argument(
        "--registry-dir",
        type=Path,
        default=None,
        help="Override registry output directory (local/test only)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Disable dry-run mode (required with --write-registry)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    dry_run = not args.no_dry_run
    if args.write_registry and dry_run:
        print("Error: --write-registry requires --no-dry-run", file=sys.stderr)
        return 2

    config = RunnerConfig(
        commodity_code=args.commodity_code,
        model_code=args.model_code,
        horizon_label=args.horizon,
        min_history=args.min_history,
        folds=args.folds,
        dry_run=dry_run,
        allow_registry_write=args.write_registry,
        registry_dir=args.registry_dir,
    )

    session = None
    if args.use_db:
        from app.db.session import get_session_factory  # noqa: WPS433

        session = get_session_factory()()

    runner = ForecastRunner(session=session)
    try:
        results = runner.run(config)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if session is not None:
            session.close()

    payload = [result.to_metadata_dict() for result in results]
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())