"""Production ``CommodityPricePredictor`` — class facade over the repo forecast contract.

Encapsulates the behavior of ``ml.forecast.forecast_commodity`` (deep-research
spec ``docs/deep-research-report-baotoandongtien.md``):

- configuration-driven (no per-commodity hardcoding)
- min history 252, horizons (30, 90), naive + 2% switch margin
- walk-forward candidate pool: ridge_ar / gbm / gbm_cyc / ou / mechanistic_fourier_supply
- point-in-time exogenous features from ``mv_ml_daily_features_wide``
- fail-closed unavailable payloads; no DB writes in the class

``mechanistic_fourier_supply`` is auto-enabled only when supply driver columns
(planted_area, import_volume, inventory) are present — never the global default.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Self

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ml.backtests.walk_forward import (
    walk_forward_ar,
    walk_forward_gbm,
    walk_forward_mechanistic,
    walk_forward_ou,
)
from ml.features.cycles import select_cycles
from ml.forecast import (
    MIN_HISTORY,
    OU_ENABLED,
    SWITCH_MARGIN,
    Z_80,
    impute_exog,
    load_price_series,
    select_candidate,
)
from ml.models.cash_flow_predictor import SupplyConfig
from ml.models.gbm_forecaster import GBMForecaster
from ml.models.gbm_forecaster import is_available as gbm_available
from ml.models.mechanistic_fourier import (
    MechanisticFourierForecaster,
    build_supply_frame,
)
from ml.models.ou_forecaster import OUForecaster
from ml.models.ridge_forecaster import RidgeARForecaster

logger = logging.getLogger(__name__)

ARTIFACT_VERSION = "cpp-v1"


def _next_business_days(last: date, count: int) -> list[date]:
    out: list[date] = []
    cursor = last
    while len(out) < count:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:
            out.append(cursor)
    return out


def _naive_interval(
    y_anchor: float, ret_sigma: float, steps: int, *, z: float = Z_80
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    point = np.repeat(float(y_anchor), steps)
    s = np.arange(1, steps + 1)
    band = z * ret_sigma * np.sqrt(s)
    return point, point * np.exp(-band), point * np.exp(band)


def _business_days_ahead(start: date, n: int) -> date:
    return _next_business_days(start, n)[-1]


class CommodityPredictorError(Exception):
    """Base error for the production predictor."""


class InsufficientHistoryError(CommodityPredictorError):
    """Fewer than ``min_history`` positive prices."""


class UnknownCommodityError(CommodityPredictorError):
    """Commodity code not found in the dimension table."""


class InvalidSeriesError(CommodityPredictorError):
    """Price frame missing required columns or empty after cleaning."""


class CommodityPricePredictor:
    """Production forecast facade matching ``forecast_commodity`` payloads."""

    def __init__(
        self,
        *,
        horizons: tuple[int, ...] = (30, 90),
        min_history: int = MIN_HISTORY,
        switch_margin: float = SWITCH_MARGIN,
        folds: int = 5,
        min_train: int = 252,
        l2: float = 5.0,
        z_interval: float = Z_80,
        enable_gbm: bool | None = None,
        enable_ou: bool = OU_ENABLED,
        enable_mechanistic_fourier: bool | None = None,
        supply_config: SupplyConfig | None = None,
        strict: bool = False,
        artifact_version: str = ARTIFACT_VERSION,
    ) -> None:
        self.horizons = horizons
        self.min_history = min_history
        self.switch_margin = switch_margin
        self.folds = folds
        self.min_train = min_train
        self.l2 = l2
        self.z_interval = z_interval
        self.enable_gbm = enable_gbm
        self.enable_ou = enable_ou
        self.enable_mechanistic_fourier = enable_mechanistic_fourier
        self.supply_config = supply_config or SupplyConfig()
        self.strict = strict
        self.artifact_version = artifact_version

        self._fitted = False
        self._unavailable: dict[str, Any] | None = None
        self._dates: list[date] = []
        self._values: list[float] = []
        self._y: np.ndarray | None = None
        self._logy: np.ndarray | None = None
        self._doy: np.ndarray | None = None
        self._exog: np.ndarray | None = None
        self._exog_names: list[str] = []
        self._supply_daily: pd.DataFrame | None = None
        self._ret_sigma: float = 0.0
        self._rpy: float = 1.0
        self._meta: dict[str, Any] = {}

    def fit(
        self,
        price_df: pd.DataFrame,
        exog_df: pd.DataFrame | None = None,
        *,
        commodity_code: str | None = None,
        instrument_code: str | None = None,
        currency: str | None = None,
    ) -> Self:
        """Pure in-memory fit. ``price_df`` needs ``date`` + ``value`` (or ``price``)."""
        if price_df is None or price_df.empty:
            raise InvalidSeriesError("price_df is empty")
        df = price_df.copy()
        if "value" not in df.columns and "price" in df.columns:
            df = df.rename(columns={"price": "value"})
        if "date" not in df.columns or "value" not in df.columns:
            raise InvalidSeriesError("price_df requires date and value (or price) columns")
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["date", "value"]).sort_values("date")
        clean = [(d, float(v)) for d, v in zip(df["date"], df["value"], strict=True) if v > 0]
        dates = [c[0] for c in clean]
        values = [c[1] for c in clean]
        code = (commodity_code or "UNKNOWN").upper()
        base = {
            "commodity_code": code,
            "instrument_code": instrument_code,
            "currency": currency,
            "model": "ridge_ar",
        }
        if len(values) < self.min_history:
            payload = {
                **base,
                "available": False,
                "reason": f"need >= {self.min_history} positive prices, have {len(values)}",
            }
            if self.strict:
                raise InsufficientHistoryError(payload["reason"])
            self._unavailable = payload
            self._fitted = True
            self._dates, self._values = dates, values
            self._meta = base
            return self

        exog, exog_names = self._prepare_exog_frame(exog_df, dates)
        self._set_prepared(dates, values, exog, base, exog_names=exog_names)
        self._unavailable = None
        self._fitted = True
        return self

    def fit_from_session(self, session: Session, commodity_code: str, *, as_of: date | None = None) -> Self:
        """Load primary series + feature view from a SQLAlchemy session (read-only)."""
        del as_of  # reserved; production path always uses the full latest history
        loaded = load_price_series(session, commodity_code)
        code = commodity_code.upper()
        if loaded is None:
            payload = {"available": False, "reason": "unknown commodity", "commodity_code": code}
            if self.strict:
                raise UnknownCommodityError(code)
            self._unavailable = payload
            self._fitted = True
            self._meta = {"commodity_code": code}
            return self

        commodity = loaded["commodity"]
        instrument = loaded["instrument"]
        dates: list[date] = list(loaded["dates"])
        values: list[float] = list(loaded["values"])
        base: dict[str, Any] = {
            "commodity_code": commodity.commodity_code,
            "instrument_code": instrument.instrument_code if instrument else None,
            "currency": instrument.currency if instrument else None,
            "model": "ridge_ar",
        }
        clean = [(d, v) for d, v in zip(dates, values, strict=True) if v > 0]
        dates = [c[0] for c in clean]
        values = [c[1] for c in clean]
        if len(values) < self.min_history:
            payload = {
                **base,
                "available": False,
                "reason": f"need >= {self.min_history} positive prices, have {len(values)}",
            }
            if self.strict:
                raise InsufficientHistoryError(payload["reason"])
            self._unavailable = payload
            self._fitted = True
            self._dates, self._values = dates, values
            self._meta = base
            return self

        exog, exog_names = self._load_exog_from_session(session, commodity.commodity_key, dates)
        self._set_prepared(dates, values, exog, base, exog_names=exog_names)
        self._unavailable = None
        self._fitted = True
        return self

    def forecast(self, *, horizons: tuple[int, ...] | None = None) -> dict[str, Any]:
        """Full production payload (same shape as ``forecast_commodity``)."""
        self._require_fitted()
        if self._unavailable is not None:
            return dict(self._unavailable)

        assert self._y is not None and self._logy is not None and self._doy is not None
        assert self._exog is not None
        hz = horizons if horizons is not None else self.horizons
        y = self._y
        logy = self._logy
        doy = self._doy
        exog_features = self._exog
        dates = self._dates
        values = self._values
        ret_sigma = self._ret_sigma
        rpy = self._rpy
        anchor_idx = len(values) - 1
        y_anchor = float(values[-1])
        use_gbm = gbm_available() if self.enable_gbm is None else bool(self.enable_gbm)
        supply_daily = self._supply_daily
        use_mech = self.enable_mechanistic_fourier
        if use_mech is None:
            use_mech = supply_daily is not None
        else:
            use_mech = bool(use_mech) and supply_daily is not None

        horizon_out: dict[str, Any] = {}
        for h in hz:
            future_dates = _next_business_days(dates[-1], h)
            ar = walk_forward_ar(
                dates,
                y,
                horizon=h,
                folds=self.folds,
                min_train=self.min_train,
                l2=self.l2,
                exog_features=exog_features,
            )
            naive_mape = ar.naive_mape
            candidates: dict[str, float] = {"ridge_ar": ar.model_mape}
            builders: dict[str, Any] = {
                "ridge_ar": lambda hh=h: RidgeARForecaster(horizon=hh, l2=self.l2).fit(
                    logy, doy, exog_features=exog_features
                )
            }
            if use_gbm:
                gb = walk_forward_gbm(
                    dates,
                    y,
                    horizon=h,
                    folds=self.folds,
                    min_train=self.min_train,
                    exog_features=exog_features,
                )
                candidates["gbm"] = gb.model_mape
                builders["gbm"] = lambda hh=h: GBMForecaster(horizon=hh).fit(logy, doy, exog_features=exog_features)
                prod_cycles = select_cycles(logy, doy, rows_per_year=rpy, horizon=h)
                if prod_cycles:
                    gbc = walk_forward_gbm(
                        dates,
                        y,
                        horizon=h,
                        folds=self.folds,
                        min_train=self.min_train,
                        use_cycles=True,
                        exog_features=exog_features,
                    )
                    candidates["gbm_cyc"] = gbc.model_mape
                    builders["gbm_cyc"] = lambda hh=h, pp=tuple(prod_cycles): GBMForecaster(
                        horizon=hh, cycle_periods=pp
                    ).fit(logy, doy, exog_features=exog_features)

            if self.enable_ou:
                ou = walk_forward_ou(dates, y, horizon=h, folds=self.folds, min_train=self.min_train)
                candidates["ou"] = ou.model_mape
                builders["ou"] = lambda hh=h: OUForecaster(horizon=hh).fit(logy, doy)

            if use_mech and supply_daily is not None:
                mech = walk_forward_mechanistic(
                    dates,
                    y,
                    supply_daily,
                    horizon=h,
                    folds=self.folds,
                    min_train=self.min_train,
                    config=self.supply_config,
                )
                candidates["mechanistic_fourier_supply"] = mech.model_mape
                builders["mechanistic_fourier_supply"] = lambda hh=h: MechanisticFourierForecaster(
                    horizon=hh, config=self.supply_config
                ).fit(logy, doy, dates=dates, supply_daily=supply_daily)

            model_used, chosen_mape = select_candidate(candidates, naive_mape, margin=self.switch_margin)
            if model_used != "naive":
                model = builders[model_used]()
                point, lower, upper = model.forecast_interval(
                    logy,
                    doy,
                    anchor_idx,
                    y_anchor,
                    h,
                    exog_features=exog_features,
                    z=self.z_interval,
                )
            else:
                point, lower, upper = _naive_interval(y_anchor, ret_sigma, h, z=self.z_interval)

            horizon_out[str(h)] = {
                "model_used": model_used,
                "points": [
                    {
                        "date": d.isoformat(),
                        "value": round(float(pt), 4),
                        "lower": round(float(lo), 4),
                        "upper": round(float(hi), 4),
                    }
                    for d, pt, lo, hi in zip(future_dates, point, lower, upper, strict=True)
                ],
                "backtest": {
                    "folds": ar.folds,
                    "mape_pct": round(chosen_mape, 2) if np.isfinite(chosen_mape) else None,
                    "naive_mape_pct": round(naive_mape, 2) if np.isfinite(naive_mape) else None,
                    "beats_naive": model_used != "naive",
                    "candidates": {k: round(v, 2) for k, v in candidates.items() if np.isfinite(v)},
                    "ou_considered": bool(self.enable_ou),
                    "mechanistic_considered": bool(use_mech),
                },
            }

        return {
            **self._meta,
            "available": True,
            "history_points": len(values),
            "last_date": dates[-1].isoformat(),
            "last_price": round(values[-1], 4),
            "horizons": horizon_out,
        }

    def predict(
        self,
        *,
        horizon: int = 30,
        future_dates: Iterable[date] | None = None,
        return_df: bool = True,
    ) -> pd.DataFrame | np.ndarray:
        """Point forecast only for one horizon."""
        del future_dates  # production path always uses business-day schedule from last date
        result = self.forecast(horizons=(horizon,))
        if not result.get("available"):
            empty = pd.DataFrame(columns=["date", "value", "lower", "upper"])
            return empty if return_df else np.empty(0)
        points = result["horizons"][str(horizon)]["points"]
        frame = pd.DataFrame(points)
        if return_df:
            return frame
        return frame["value"].to_numpy(dtype=float)

    def explain(self, *, horizon: int = 30) -> dict[str, Any]:
        result = self.forecast(horizons=(horizon,))
        if not result.get("available"):
            return {"available": False, "reason": result.get("reason"), "horizon": horizon}
        hz = result["horizons"][str(horizon)]
        return {
            "available": True,
            "commodity_code": result["commodity_code"],
            "instrument_code": result.get("instrument_code"),
            "horizon": horizon,
            "model_used": hz["model_used"],
            "backtest": hz["backtest"],
            "last_date": result["last_date"],
            "last_price": result["last_price"],
            "artifact_version": self.artifact_version,
        }

    def evaluate(
        self,
        actual_df: pd.DataFrame,
        *,
        metric_set: tuple[str, ...] = ("mae", "rmse", "mape"),
        horizon: int = 30,
    ) -> dict[str, Any]:
        """Offline join of a prior ``predict`` path against realized prices."""
        pred = self.predict(horizon=horizon, return_df=True)
        assert isinstance(pred, pd.DataFrame)
        if pred.empty or actual_df is None or actual_df.empty:
            return {"n": 0, "metrics": {}}
        act = actual_df.copy()
        if "value" not in act.columns and "price" in act.columns:
            act = act.rename(columns={"price": "value"})
        act["date"] = pd.to_datetime(act["date"]).dt.date.astype(str)
        merged = pred.merge(act[["date", "value"]], on="date", suffixes=("_pred", "_actual"))
        if merged.empty:
            return {"n": 0, "metrics": {}}
        y_true = merged["value_actual"].to_numpy(dtype=float)
        y_pred = merged["value_pred"].to_numpy(dtype=float)
        err = y_pred - y_true
        metrics: dict[str, float] = {}
        if "mae" in metric_set:
            metrics["mae"] = float(np.mean(np.abs(err)))
        if "rmse" in metric_set:
            metrics["rmse"] = float(np.sqrt(np.mean(err**2)))
        if "mape" in metric_set:
            denom = np.where(np.abs(y_true) < 1e-12, np.nan, np.abs(y_true))
            metrics["mape"] = float(np.nanmean(np.abs(err) / denom) * 100.0)
        return {"n": int(len(merged)), "metrics": metrics, "joined": merged}

    @staticmethod
    def to_forecast_log_rows(
        result: dict[str, Any],
        *,
        run_id: str,
        run_mode: str,
        version: str = ARTIFACT_VERSION,
        allowed_horizons: tuple[int, ...] = (30, 90),
    ) -> list[dict[str, Any]]:
        """Build pending forecast-log row dicts (no DB write)."""
        if not result or not result.get("available"):
            return []
        code, last_date, last_price = (
            result.get("commodity_code"),
            result.get("last_date"),
            result.get("last_price"),
        )
        if not (code and last_date and last_price):
            return []
        as_of = date.fromisoformat(str(last_date))
        baseline = float(last_price)
        rows: list[dict[str, Any]] = []
        for h_str, hz in (result.get("horizons") or {}).items():
            try:
                horizon = int(h_str)
            except (TypeError, ValueError):
                continue
            if horizon not in allowed_horizons:
                continue
            points = hz.get("points") or []
            if not points:
                continue
            try:
                predicted = float(points[-1]["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if predicted <= 0:
                continue
            bt = hz.get("backtest") or {}
            rows.append(
                {
                    "forecast_run_id": run_id,
                    "commodity_code": code,
                    "as_of_date": as_of,
                    "target_date": _business_days_ahead(as_of, horizon),
                    "horizon_days": horizon,
                    "model_used": hz.get("model_used") or "naive",
                    "predicted_price": predicted,
                    "baseline_price": baseline,
                    "status": "pending",
                    "metadata_json": {
                        "candidates": bt.get("candidates"),
                        "ou_considered": bt.get("ou_considered"),
                        "mape_pct": bt.get("mape_pct"),
                        "naive_mape_pct": bt.get("naive_mape_pct"),
                        "beats_naive": bt.get("beats_naive"),
                        "source": "forecast_commodity",
                        "run_mode": run_mode,
                        "version": version,
                    },
                }
            )
        return rows

    def save(self, path: str | Path) -> Path:
        """Persist fitted series + metadata (stdlib pickle + version manifest)."""
        import pickle

        self._require_fitted()
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "artifact_version": self.artifact_version,
            "config": {
                "horizons": self.horizons,
                "min_history": self.min_history,
                "switch_margin": self.switch_margin,
                "folds": self.folds,
                "min_train": self.min_train,
                "l2": self.l2,
                "z_interval": self.z_interval,
                "enable_gbm": self.enable_gbm,
                "enable_ou": self.enable_ou,
                "enable_mechanistic_fourier": self.enable_mechanistic_fourier,
            },
            "meta": self._meta,
            "unavailable": self._unavailable,
            "dates": self._dates,
            "values": self._values,
            "exog": self._exog,
            "exog_names": self._exog_names,
            "ret_sigma": self._ret_sigma,
            "rpy": self._rpy,
        }
        with out.open("wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        return out

    @classmethod
    def load(cls, path: str | Path) -> CommodityPricePredictor:
        import pickle

        with Path(path).open("rb") as fh:
            payload = pickle.load(fh)
        if payload.get("artifact_version") != ARTIFACT_VERSION:
            raise CommodityPredictorError(
                f"artifact version mismatch: {payload.get('artifact_version')} != {ARTIFACT_VERSION}"
            )
        cfg = payload["config"]
        obj = cls(
            horizons=tuple(cfg["horizons"]),
            min_history=int(cfg["min_history"]),
            switch_margin=float(cfg["switch_margin"]),
            folds=int(cfg["folds"]),
            min_train=int(cfg["min_train"]),
            l2=float(cfg["l2"]),
            z_interval=float(cfg["z_interval"]),
            enable_gbm=cfg["enable_gbm"],
            enable_ou=bool(cfg["enable_ou"]),
            enable_mechanistic_fourier=cfg.get("enable_mechanistic_fourier"),
            artifact_version=str(payload["artifact_version"]),
        )
        obj._meta = dict(payload["meta"])
        obj._unavailable = payload["unavailable"]
        obj._dates = list(payload["dates"])
        obj._values = list(payload["values"])
        if obj._unavailable is None and obj._values:
            obj._set_prepared(
                obj._dates,
                obj._values,
                np.asarray(payload["exog"], dtype=float)
                if payload["exog"] is not None
                else np.empty((len(obj._values), 0)),
                obj._meta,
                exog_names=list(payload.get("exog_names") or []),
            )
        else:
            obj._exog = np.asarray(payload["exog"], dtype=float) if payload["exog"] is not None else np.empty((0, 0))
            obj._ret_sigma = float(payload.get("ret_sigma", 0.0))
            obj._rpy = float(payload.get("rpy", 1.0))
        obj._fitted = True
        return obj

    def _set_prepared(
        self,
        dates: list[date],
        values: list[float],
        exog: np.ndarray,
        meta: dict[str, Any],
        *,
        exog_names: list[str] | None = None,
    ) -> None:
        y = np.asarray(values, dtype=float)
        logy = np.log(y)
        doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
        self._dates = dates
        self._values = values
        self._y = y
        self._logy = logy
        self._doy = doy
        self._exog = exog
        self._exog_names = list(exog_names or [])
        self._supply_daily = build_supply_frame(dates, y, exog, self._exog_names or None)
        self._ret_sigma = float(np.std(np.diff(logy), ddof=1)) if len(logy) > 1 else 0.0
        span_days = max(1, (dates[-1] - dates[0]).days)
        self._rpy = len(values) / (span_days / 365.25)
        self._meta = meta

    def _prepare_exog_frame(self, exog_df: pd.DataFrame | None, dates: list[date]) -> tuple[np.ndarray, list[str]]:
        if exog_df is None or exog_df.empty:
            return np.empty((len(dates), 0)), []
        df = exog_df.copy()
        if "as_of_date" in df.columns:
            df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.date
            df = df.set_index("as_of_date")
        elif not isinstance(df.index, pd.DatetimeIndex) and df.index.name != "as_of_date":
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.date
                df = df.set_index("date")
        if isinstance(df.index, pd.DatetimeIndex):
            df.index = df.index.date
        drop_cols = [c for c in ["commodity_key", "price_close"] if c in df.columns]
        if drop_cols:
            df = df.drop(columns=drop_cols)
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        nan_cols = df.columns[df.isna().all()].tolist()
        if nan_cols:
            df = df.drop(columns=nan_cols)
        df = impute_exog(df, dates)
        names = [str(c) for c in df.columns.tolist()]
        return df.to_numpy(dtype=float), names

    def _load_exog_from_session(
        self, session: Session, commodity_key: int, dates: list[date]
    ) -> tuple[np.ndarray, list[str]]:
        from sqlalchemy import text

        view_query = text("SELECT * FROM mv_ml_daily_features_wide WHERE commodity_key = :key ORDER BY as_of_date")
        res = session.execute(view_query, {"key": commodity_key})
        data = res.fetchall()
        if not data:
            return np.empty((len(dates), 0)), []
        cols = list(res.keys())
        df_view = pd.DataFrame(data, columns=cols)
        df_view["as_of_date"] = pd.to_datetime(df_view["as_of_date"]).dt.date
        df_view = df_view.set_index("as_of_date")
        drop_cols = [c for c in ["commodity_key", "price_close"] if c in df_view.columns]
        df_view = df_view.drop(columns=drop_cols)
        for c in df_view.columns:
            df_view[c] = pd.to_numeric(df_view[c], errors="coerce")
        nan_cols = df_view.columns[df_view.isna().all()].tolist()
        if nan_cols:
            logger.warning("Dropping columns due to non-numeric garbage: %s", nan_cols)
            df_view = df_view.drop(columns=nan_cols)
        df_view = impute_exog(df_view, dates)
        names = [str(c) for c in df_view.columns.tolist()]
        logger.info("Final exog_feature_names passed to model: %s", names)
        return df_view.to_numpy(dtype=float), names

    def _require_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("call fit() or fit_from_session() before forecast/predict")
