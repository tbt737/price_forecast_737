"""Model Registry (Phase 7A).

Manages versioned model metadata and backtest performance in local JSON files.
Writes are opt-in via ``allow_write``; no filesystem side effects at import time.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.backtests.walk_forward import BacktestResult

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "data" / "models"


@dataclass
class ModelMetadata:
    commodity_code: str
    model_code: str
    family: str
    horizon: str
    version: int
    features_used: list[str]
    hyperparameters: dict[str, Any]
    backtest: BacktestResult
    trained_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "commodity_code": self.commodity_code,
            "model_code": self.model_code,
            "family": self.family,
            "horizon": self.horizon,
            "version": self.version,
            "features_used": self.features_used,
            "hyperparameters": self.hyperparameters,
            "backtest": asdict(self.backtest),
            "trained_at": self.trained_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelMetadata:
        bt_data = data["backtest"]
        bt = BacktestResult(
            horizon=bt_data["horizon"],
            folds=bt_data["folds"],
            model_mape=bt_data["model_mape"],
            model_rmse=bt_data["model_rmse"],
            naive_mape=bt_data["naive_mape"],
        )
        return cls(
            commodity_code=data["commodity_code"],
            model_code=data["model_code"],
            family=data["family"],
            horizon=data["horizon"],
            version=data["version"],
            features_used=data["features_used"],
            hyperparameters=data["hyperparameters"],
            backtest=bt,
            trained_at=data["trained_at"],
        )


def _resolve_registry_dir(registry_dir: Path | None) -> Path:
    return registry_dir if registry_dir is not None else REGISTRY_DIR


def _get_registry_file(registry_dir: Path, commodity_code: str, model_code: str) -> Path:
    return registry_dir / f"{commodity_code.lower()}_{model_code.lower()}.json"


def _ensure_registry_dir(registry_dir: Path) -> None:
    registry_dir.mkdir(parents=True, exist_ok=True)


def register_model(
    commodity_code: str,
    model_code: str,
    family: str,
    horizon: str,
    features_used: list[str],
    hyperparameters: dict[str, Any],
    backtest: BacktestResult,
    *,
    registry_dir: Path | None = None,
    allow_write: bool = False,
    trained_at: str | None = None,
) -> ModelMetadata:
    """Register a successful backtest. Skips disk writes unless ``allow_write=True``."""
    resolved_dir = _resolve_registry_dir(registry_dir)
    path = _get_registry_file(resolved_dir, commodity_code, model_code)

    version = 1
    if path.exists():
        existing = json.loads(path.read_text("utf-8"))
        version = int(existing.get("version", 0)) + 1

    timestamp = trained_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    metadata = ModelMetadata(
        commodity_code=commodity_code,
        model_code=model_code,
        family=family,
        horizon=horizon,
        version=version,
        features_used=features_used,
        hyperparameters=hyperparameters,
        backtest=backtest,
        trained_at=timestamp,
    )

    if allow_write:
        _ensure_registry_dir(resolved_dir)
        path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")

    return metadata


def load_latest_model(
    commodity_code: str,
    model_code: str,
    *,
    registry_dir: Path | None = None,
) -> ModelMetadata | None:
    """Load the latest registered model metadata."""
    resolved_dir = _resolve_registry_dir(registry_dir)
    path = _get_registry_file(resolved_dir, commodity_code, model_code)
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    return ModelMetadata.from_dict(data)


def find_best_model(commodity_code: str, *, registry_dir: Path | None = None) -> ModelMetadata | None:
    """Find the best model for a commodity based on out-of-sample MAPE."""
    resolved_dir = _resolve_registry_dir(registry_dir)
    if not resolved_dir.exists():
        return None

    best: ModelMetadata | None = None
    for path in resolved_dir.glob(f"{commodity_code.lower()}_*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = ModelMetadata.from_dict(data)
        if meta.backtest.beats_naive and (best is None or meta.backtest.model_mape < best.backtest.model_mape):
            best = meta

    return best