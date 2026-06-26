"""Internal ML forecast runner (Phase 7A).

Orchestrates walk-forward backtests using the Phase 6 model layer. Defaults to
dry-run / no-write. DB access requires an injected session — nothing connects at
import time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import yaml

from ml.backtests.walk_forward import BacktestResult, walk_forward_ar, walk_forward_gbm
from ml.models.gbm_forecaster import is_available as gbm_available
from ml.registry.core import register_model

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROFILES_DIR = _REPO_ROOT / "configs" / "commodities"

MIN_HISTORY_DEFAULT = 300
VALID_HORIZON_LABELS = frozenset({"daily", "weekly", "monthly"})
HORIZON_DAYS = {"daily": 1, "weekly": 5, "monthly": 21}

METRIC_NAMES = ("model_mape", "model_rmse", "naive_mape", "beats_naive", "folds")


class RunnerError(Exception):
    """Base error for guarded runner failures."""


class InsufficientHistoryError(RunnerError):
    """Raised when the price series is too short for a walk-forward backtest."""


class InvalidHorizonError(RunnerError):
    """Raised when horizon configuration is missing or unsupported."""


class MissingDataError(RunnerError):
    """Raised when neither inline data nor an injected session is provided."""


class MissingHorizonError(MissingDataError):
    def __init__(self, horizon_label: str, commodity_code: str) -> None:
        super().__init__(
            f"no models with horizon={horizon_label!r} configured for commodity_code={commodity_code!r}"
        )


class UnknownCommodityError(RunnerError):
    """Raised when the commodity profile cannot be loaded."""


class UnsupportedModelFamilyError(RunnerError):
    """Raised when a profile model family has no backtest implementation."""


class Session(Protocol):
    def execute(self, statement: Any, params: dict[str, Any] | None = ...) -> Any: ...


@dataclass(frozen=True)
class PriceSeriesData:
    dates: list[date]
    values: np.ndarray
    feature_names: list[str] = field(default_factory=list)
    exog_features: np.ndarray | None = None

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.values):
            raise ValueError("dates and values must have the same length")
        if self.exog_features is not None and len(self.exog_features) != len(self.values):
            raise ValueError("exog_features must align with values")


@dataclass
class RunnerConfig:
    commodity_code: str
    model_code: str | None = None
    horizon_label: str | None = None
    min_history: int = MIN_HISTORY_DEFAULT
    folds: int = 5
    l2: float = 5.0
    dry_run: bool = True
    allow_registry_write: bool = False
    registry_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.min_history < 1:
            raise InvalidHorizonError("min_history must be >= 1")
        if self.folds < 1:
            raise InvalidHorizonError("folds must be >= 1")
        if self.allow_registry_write and self.dry_run:
            raise ValueError("allow_registry_write requires dry_run=False")
        if self.horizon_label is not None and self.horizon_label not in VALID_HORIZON_LABELS:
            raise InvalidHorizonError(
                f"unsupported horizon_label={self.horizon_label!r}; "
                f"expected one of {sorted(VALID_HORIZON_LABELS)}"
            )


@dataclass
class RunnerResult:
    commodity_code: str
    model_code: str
    family: str
    horizon_label: str
    horizon_days: int
    training_window_start: str | None
    training_window_end: str | None
    training_observations: int
    feature_count: int
    feature_names: list[str]
    metrics: dict[str, float | int | bool]
    fallback_used: bool
    dry_run: bool
    registered: bool
    backtest: BacktestResult

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "commodity_code": self.commodity_code,
            "model_code": self.model_code,
            "model_type": self.family,
            "horizon": self.horizon_label,
            "horizon_days": self.horizon_days,
            "training_window": {
                "start": self.training_window_start,
                "end": self.training_window_end,
                "observations": self.training_observations,
            },
            "feature_count": self.feature_count,
            "feature_names": self.feature_names,
            "metrics": self.metrics,
            "fallback_used": self.fallback_used,
            "dry_run": self.dry_run,
            "registered": self.registered,
            "backtest": asdict(self.backtest),
        }


def load_commodity_profile(commodity_code: str) -> dict[str, Any]:
    profile_path = _PROFILES_DIR / f"{commodity_code.lower()}.yaml"
    if not profile_path.exists():
        raise UnknownCommodityError(f"profile not found for commodity_code={commodity_code!r}")
    return yaml.safe_load(profile_path.read_text("utf-8"))


def horizon_label_to_days(horizon_label: str) -> int:
    if horizon_label not in HORIZON_DAYS:
        raise InvalidHorizonError(f"unsupported horizon_label={horizon_label!r}")
    return HORIZON_DAYS[horizon_label]


def _select_models(profile: dict[str, Any], config: RunnerConfig) -> list[dict[str, Any]]:
    models = profile.get("models") or []
    if not models:
        raise MissingDataError(f"no models configured for commodity_code={config.commodity_code!r}")
    if config.model_code is not None:
        selected = [m for m in models if m.get("model_code") == config.model_code]
        if not selected:
            raise MissingDataError(
                f"model_code={config.model_code!r} not found in profile for {config.commodity_code!r}"
            )
        return selected
    if config.horizon_label is not None:
        selected = [m for m in models if m.get("horizon") == config.horizon_label]
        if not selected:
            raise MissingHorizonError(config.horizon_label, config.commodity_code)
        return selected
    return list(models)


def _run_walk_forward(
    family: str,
    *,
    dates: list[date],
    values: np.ndarray,
    horizon_days: int,
    folds: int,
    l2: float,
    exog_features: np.ndarray | None,
) -> BacktestResult:
    if family in {"statsmodels", "fourier"}:
        return walk_forward_ar(dates, values, horizon=horizon_days, folds=folds, l2=l2, exog_features=exog_features)
    if family == "xgboost":
        if not gbm_available():
            raise UnsupportedModelFamilyError("xgboost family requested but xgboost is not installed")
        return walk_forward_gbm(
            dates, values, horizon=horizon_days, folds=folds, use_cycles=True, exog_features=exog_features
        )
    if family == "prophet":
        raise UnsupportedModelFamilyError("prophet family is not implemented in the internal runner yet")
    raise UnsupportedModelFamilyError(f"unsupported model family={family!r}")


def _positive_price_series(data: PriceSeriesData) -> PriceSeriesData:
    mask = data.values > 0
    if not mask.any():
        raise InsufficientHistoryError("no positive prices available")
    dates = [d for d, keep in zip(data.dates, mask, strict=True) if keep]
    values = data.values[mask]
    exog = data.exog_features[mask] if data.exog_features is not None else None
    return PriceSeriesData(
        dates=dates,
        values=values,
        feature_names=list(data.feature_names),
        exog_features=exog,
    )


def _validate_history(data: PriceSeriesData, min_history: int, horizon_days: int) -> None:
    if len(data.values) < min_history:
        raise InsufficientHistoryError(
            f"need >= {min_history} observations, found {len(data.values)}"
        )
    if len(data.values) <= horizon_days:
        raise InvalidHorizonError(
            f"horizon_days={horizon_days} requires more than {horizon_days} observations"
        )


def run_model_backtest(
    data: PriceSeriesData,
    model_entry: dict[str, Any],
    config: RunnerConfig,
) -> RunnerResult:
    family = str(model_entry.get("family", ""))
    model_code = str(model_entry.get("model_code", ""))
    horizon_label = str(model_entry.get("horizon", ""))
    if not model_code:
        raise MissingDataError("model entry missing model_code")
    if horizon_label not in VALID_HORIZON_LABELS:
        raise InvalidHorizonError(f"model {model_code!r} has invalid horizon={horizon_label!r}")

    horizon_days = horizon_label_to_days(horizon_label)
    clean = _positive_price_series(data)
    _validate_history(clean, config.min_history, horizon_days)

    backtest = _run_walk_forward(
        family,
        dates=clean.dates,
        values=clean.values,
        horizon_days=horizon_days,
        folds=config.folds,
        l2=config.l2,
        exog_features=clean.exog_features,
    )

    feature_names = list(clean.feature_names) or ["target_price"]
    if clean.exog_features is not None and not clean.feature_names:
        feature_names = [f"exog_{i}" for i in range(clean.exog_features.shape[1])]
        feature_names = ["target_price", *feature_names]

    metrics: dict[str, float | int | bool] = {
        "model_mape": backtest.model_mape,
        "model_rmse": backtest.model_rmse,
        "naive_mape": backtest.naive_mape,
        "beats_naive": backtest.beats_naive,
        "folds": backtest.folds,
    }
    fallback_used = not backtest.beats_naive
    registered = False

    if not config.dry_run and backtest.beats_naive:
        register_model(
            commodity_code=config.commodity_code,
            model_code=model_code,
            family=family,
            horizon=horizon_label,
            features_used=feature_names,
            hyperparameters={"horizon_days": horizon_days, "folds": config.folds, "l2": config.l2},
            backtest=backtest,
            registry_dir=config.registry_dir,
            allow_write=config.allow_registry_write,
        )
        registered = config.allow_registry_write

    return RunnerResult(
        commodity_code=config.commodity_code.upper(),
        model_code=model_code,
        family=family,
        horizon_label=horizon_label,
        horizon_days=horizon_days,
        training_window_start=clean.dates[0].isoformat(),
        training_window_end=clean.dates[-1].isoformat(),
        training_observations=len(clean.values),
        feature_count=len(feature_names),
        feature_names=feature_names,
        metrics=metrics,
        fallback_used=fallback_used,
        dry_run=config.dry_run,
        registered=registered,
        backtest=backtest,
    )


def load_price_series_from_session(session: Session, commodity_code: str) -> PriceSeriesData:
    """Load aligned price + exogenous features via an injected DB session."""
    from sqlalchemy import text

    query = text(
        """
        SELECT as_of_date AS obs_date, price_close AS target_price
        FROM mv_ml_daily_features_wide
        WHERE commodity_key = (
            SELECT commodity_key FROM dim_commodity WHERE commodity_code = :code
        )
          AND price_close IS NOT NULL
        ORDER BY as_of_date ASC
        """
    )
    rows = session.execute(query, {"code": commodity_code.upper()}).fetchall()
    if not rows:
        raise MissingDataError(f"no feature-view rows found for commodity_code={commodity_code!r}")

    dates = [r.obs_date for r in rows]
    values = np.array([float(r.target_price) for r in rows], dtype=float)
    return PriceSeriesData(dates=dates, values=values, feature_names=["target_price"])


class ForecastRunner:
    """Guarded internal runner — dry-run by default, session injected on demand."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def run(
        self,
        config: RunnerConfig,
        *,
        data: PriceSeriesData | None = None,
    ) -> list[RunnerResult]:
        profile = load_commodity_profile(config.commodity_code)
        models = _select_models(profile, config)

        if data is None:
            if self._session is None:
                raise MissingDataError(
                    "provide inline PriceSeriesData or inject a DB session before running"
                )
            data = load_price_series_from_session(self._session, config.commodity_code)

        return [run_model_backtest(data, model_entry, config) for model_entry in models]