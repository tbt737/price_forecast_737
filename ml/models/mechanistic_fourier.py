"""Daily-pool adapter for the cash-flow + Fourier research model.

Wraps ``CashFlowFourierPredictor`` so it can sit in the production candidate
pool as ``mechanistic_fourier_supply`` (deep-research spec). Commodity-agnostic:
supply knobs come from ``SupplyConfig``; driver columns are resolved by metric
aliases, never by commodity name.

Fail-closed: if planted_area / import_volume / inventory cannot be resolved,
``has_supply_drivers`` is False and the pool must skip this candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ml.models.cash_flow_predictor import CashFlowFourierPredictor, SupplyConfig

# Metric-code aliases (config/MV column names) — not commodity names.
SUPPLY_ALIASES: dict[str, tuple[str, ...]] = {
    "planted_area": ("planted_area", "area_planted", "sown_area", "acreage"),
    "import_volume": ("import_volume", "imports", "import_qty", "import_tonnes"),
    "inventory": ("inventory", "cold_storage_inventory", "stocks", "ending_stocks"),
    "weather_index": ("weather_index", "weather", "rainfall_index"),
}


def resolve_supply_column(columns: list[str] | tuple[str, ...], role: str) -> str | None:
    """Return the first column name matching ``role`` aliases (case-insensitive)."""
    aliases = SUPPLY_ALIASES.get(role, (role,))
    lower_map = {c.lower(): c for c in columns}
    for alias in aliases:
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    return None


def has_supply_drivers(columns: list[str] | tuple[str, ...] | None) -> bool:
    if not columns:
        return False
    return all(resolve_supply_column(columns, role) for role in ("planted_area", "import_volume", "inventory"))


def _next_business_days(last: date, count: int) -> list[date]:
    out: list[date] = []
    cursor = last
    while len(out) < count:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:
            out.append(cursor)
    return out


def build_supply_frame(
    dates: list[date],
    prices: np.ndarray,
    exog: np.ndarray | None,
    exog_names: list[str] | None,
) -> pd.DataFrame | None:
    """Build a daily driver frame; None when required supply columns are missing."""
    if exog is None or exog_names is None or exog.size == 0:
        return None
    if len(exog_names) != exog.shape[1]:
        return None
    if not has_supply_drivers(exog_names):
        return None
    data: dict[str, Any] = {
        "date": list(dates),
        "price": np.asarray(prices, dtype=float),
    }
    for role in ("planted_area", "import_volume", "inventory", "weather_index"):
        col = resolve_supply_column(exog_names, role)
        if col is None:
            if role == "weather_index":
                continue
            return None
        data[role] = exog[:, exog_names.index(col)].astype(float)
    return pd.DataFrame(data)


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Month-end aggregate: last price, mean drivers (point-in-time within month)."""
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date")
    frame["ym"] = frame["date"].dt.to_period("M")
    agg: dict[str, str] = {"price": "last", "date": "last"}
    for col in ("planted_area", "import_volume", "inventory", "weather_index", "pest_index", "k"):
        if col in frame.columns:
            agg[col] = "mean"
    out = frame.groupby("ym", sort=True).agg(agg).reset_index(drop=True)
    out["date"] = pd.to_datetime(out["date"])
    return out


@dataclass
class MechanisticFourierForecaster:
    """Anchored daily forecaster backed by monthly cash-flow + Fourier fit."""

    horizon: int
    config: SupplyConfig = field(default_factory=SupplyConfig)
    ret_sigma_: float = 0.0
    _model: CashFlowFourierPredictor | None = field(default=None, repr=False)
    _last_date: date | None = None
    _anchor_price: float = 0.0

    def fit(
        self,
        logy: np.ndarray,
        doy: np.ndarray | None,
        *,
        end: int | None = None,
        dates: list[date] | None = None,
        supply_daily: pd.DataFrame | None = None,
        exog_features: np.ndarray | None = None,
    ) -> MechanisticFourierForecaster:
        del doy, exog_features  # supply comes from ``supply_daily`` only
        if dates is None or supply_daily is None:
            raise ValueError("MechanisticFourierForecaster.fit requires dates and supply_daily")
        cut = len(logy) if end is None else int(end)
        if cut < 2:
            self._model = None
            self.ret_sigma_ = 0.0
            return self

        y = np.exp(np.asarray(logy[:cut], dtype=float))
        daily = supply_daily.iloc[:cut].copy()
        daily["price"] = y
        daily["date"] = list(dates[:cut])
        monthly = to_monthly(daily)
        self._last_date = dates[cut - 1]
        self._anchor_price = float(y[-1])
        self.ret_sigma_ = float(np.std(np.diff(np.log(y)), ddof=1)) if len(y) > 1 else 0.0
        if len(monthly) < max(12, self.config.m_flow_window_months + 3):
            self._model = None
            return self

        model = CashFlowFourierPredictor(config=self.config)
        model.fit(monthly)
        self._model = model
        return self

    def forecast(
        self,
        logy: np.ndarray,
        doy: np.ndarray | None,
        anchor_idx: int,
        y_anchor: float,
        steps: int,
        *,
        exog_features: np.ndarray | None = None,
        dates: list[date] | None = None,
    ) -> np.ndarray:
        del logy, doy, anchor_idx, exog_features, dates
        if self._model is None or self._last_date is None:
            return np.repeat(float(y_anchor), steps)
        future_dates = _next_business_days(self._last_date, steps)
        month_starts = pd.date_range(
            pd.Timestamp(future_dates[0]).to_period("M").to_timestamp(),
            pd.Timestamp(future_dates[-1]).to_period("M").to_timestamp(),
            freq="MS",
        )
        monthly_fc = self._model.predict(month_starts)
        month_price = {
            (pd.Timestamp(d).year, pd.Timestamp(d).month): float(p)
            for d, p in zip(monthly_fc["date"], monthly_fc["price_pred"], strict=True)
        }
        raw = np.array(
            [month_price.get((d.year, d.month), float(y_anchor)) for d in future_dates],
            dtype=float,
        )
        if not np.isfinite(raw).all() or np.all(raw <= 0):
            return np.repeat(float(y_anchor), steps)
        scale = float(y_anchor) / float(raw[0]) if raw[0] != 0 else 1.0
        return raw * scale

    def forecast_interval(
        self,
        logy: np.ndarray,
        doy: np.ndarray | None,
        anchor_idx: int,
        y_anchor: float,
        steps: int,
        *,
        exog_features: np.ndarray | None = None,
        dates: list[date] | None = None,
        z: float = 1.2816,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        point = self.forecast(
            logy,
            doy,
            anchor_idx,
            y_anchor,
            steps,
            exog_features=exog_features,
            dates=dates,
        )
        s = np.arange(1, steps + 1)
        band = z * self.ret_sigma_ * np.sqrt(s)
        return point, point * np.exp(-band), point * np.exp(band)
