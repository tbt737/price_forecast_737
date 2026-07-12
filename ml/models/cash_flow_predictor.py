"""Cash-flow + lagged-supply price model with multi-frequency Fourier residual.

Implements the conservation-of-money-flow identity from the research note
``bao_cao_du_doan_gia_hang_hoa_v2.md``:

    P(t) = M_flow(t) / Q(t) * k(t) + P_trend(t) + P_Fourier(t)

``Q(t)`` is built from inventory, lag-harvested domestic supply, lagged imports,
and a proportional loss term. Trend + Fourier terms are OLS-fit on the residual
after subtracting the mechanical ``M/Q`` component.

Commodity-agnostic by design (CLAUDE.md §1): harvest/import lags, yield, and
loss fraction live in ``SupplyConfig`` (or a YAML profile), never in
``if commodity == "garlic"`` branches. Example lag values from the note
(dehydrated garlic ≈ 6 mo, dried chili ≈ 5 mo, onion ≈ 4 mo) belong in the
caller / profile, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("date", "price", "planted_area", "import_volume", "inventory")
OPTIONAL_DEFAULTS = {
    "weather_index": 1.0,
    "pest_index": 1.0,
    "quality_delta": 0.0,
    "import_shock": 0.0,
    "k": 1.0,
}


@dataclass(frozen=True)
class SupplyConfig:
    """Physical / seasonal knobs for one commodity series (pass from profile)."""

    harvest_lag_months: float = 6.0
    import_lag_months: float = 0.7
    yield_tonnes_per_ha: float = 10.0
    loss_fraction: float = 0.10
    m_flow_window_months: int = 12
    fourier_periods_months: tuple[float, ...] = (12.0, 6.0, 24.0)
    trend_degree: int = 2
    default_k: float = 1.0
    q_floor: float = 1e-6


@dataclass
class BacktestResult:
    mae: float
    rmse: float
    mape: float
    n_test: int
    y_true: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))
    y_pred: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))
    dates: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0, dtype="datetime64[ns]"))


def _month_index(dates: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Continuous month index relative to the first observation (Fourier timebase)."""
    ts = pd.to_datetime(pd.Series(dates))
    origin = ts.iloc[0]
    return ((ts.dt.year - origin.year) * 12 + (ts.dt.month - origin.month)).to_numpy(dtype=float)


def _shift_by_months(values: np.ndarray, months: float) -> np.ndarray:
    """Integer month lag (rounded). Leading positions become NaN then filled with 0."""
    lag = int(round(months))
    if lag <= 0:
        return values.astype(float, copy=True)
    out = np.full(len(values), np.nan, dtype=float)
    if lag < len(values):
        out[lag:] = values[:-lag]
    return np.nan_to_num(out, nan=0.0)


def _design_matrix(t: np.ndarray, *, periods: tuple[float, ...], trend_degree: int) -> np.ndarray:
    """Columns: polynomial trend (degree d) + sin/cos for each Fourier period (months)."""
    cols: list[np.ndarray] = [np.ones_like(t, dtype=float)]
    for d in range(1, trend_degree + 1):
        cols.append(np.power(t, d))
    for period in periods:
        omega = 2.0 * np.pi / float(period)
        cols.append(np.cos(omega * t))
        cols.append(np.sin(omega * t))
    return np.column_stack(cols)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    denom = np.where(np.abs(y_true) < 1e-12, np.nan, np.abs(y_true))
    mape = float(np.nanmean(np.abs(err) / denom) * 100.0)
    return mae, rmse, mape


class CashFlowFourierPredictor:
    """Mechanical cash-flow supply model + OLS trend/Fourier residual."""

    def __init__(self, config: SupplyConfig | None = None) -> None:
        self.config = config or SupplyConfig()
        self._history: pd.DataFrame | None = None
        self._t: np.ndarray | None = None
        self._m_flow_series: np.ndarray | None = None
        self._q_series: np.ndarray | None = None
        self._p_mech: np.ndarray | None = None
        self._residual_coef: np.ndarray | None = None
        self._last_m_flow: float = 0.0
        self._fitted: bool = False
        self._forecast_frame: pd.DataFrame | None = None

    def fit(
        self,
        historical_df: pd.DataFrame,
        lags: dict[str, float] | None = None,
    ) -> CashFlowFourierPredictor:
        """Fit mechanical M/Q plus trend+Fourier residual on chronological history.

        ``lags`` overrides config lags with generic keys only, e.g.
        ``{"harvest_months": 6.0, "import_months": 0.7}``. Commodity names are
        not accepted here — put those in the profile / caller.
        """
        cfg = self._apply_lag_overrides(lags)
        df = self._normalize_frame(historical_df)
        if len(df) < max(12, cfg.m_flow_window_months + 3):
            raise ValueError(f"need at least {max(12, cfg.m_flow_window_months + 3)} rows to fit; got {len(df)}")

        t = _month_index(df["date"])
        q = self._compute_q(df, cfg)
        # Revenue proxy: price * Q; trailing mean ≈ money flow into the segment.
        revenue = df["price"].to_numpy(dtype=float) * q
        window = max(1, int(cfg.m_flow_window_months))
        m_flow = pd.Series(revenue).rolling(window=window, min_periods=max(1, window // 2)).mean().to_numpy(dtype=float)
        # Point-in-time: early rows without a full window use expanding mean of past only.
        expanding = pd.Series(revenue).expanding(min_periods=1).mean().to_numpy(dtype=float)
        m_flow = np.where(np.isfinite(m_flow), m_flow, expanding)

        k = df["k"].to_numpy(dtype=float)
        p_mech = (m_flow / np.maximum(q, cfg.q_floor)) * k
        residual = df["price"].to_numpy(dtype=float) - p_mech

        x = _design_matrix(t, periods=cfg.fourier_periods_months, trend_degree=cfg.trend_degree)
        coef, *_ = np.linalg.lstsq(x, residual, rcond=None)

        self.config = cfg
        self._history = df
        self._t = t
        self._m_flow_series = m_flow
        self._q_series = q
        self._p_mech = p_mech
        self._residual_coef = coef
        self._last_m_flow = float(m_flow[-1])
        self._fitted = True
        self._forecast_frame = None
        return self

    def predict(
        self,
        future_dates: list[datetime] | pd.DatetimeIndex | pd.Series,
        future_drivers: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Forecast prices at ``future_dates``.

        Pass ``future_drivers`` with the same driver columns as fit history
        (``planted_area``, ``import_volume``, ``inventory``, optional indices).
        If omitted, the last observed drivers are carried forward (still respects
        harvest/import lags against the concatenated history).
        """
        self._require_fitted()
        assert self._history is not None and self._residual_coef is not None

        future_idx = pd.to_datetime(pd.Index(future_dates))
        if len(future_idx) == 0:
            return pd.DataFrame(
                columns=[
                    "date",
                    "price_pred",
                    "q",
                    "m_flow",
                    "p_mechanical",
                    "p_trend_fourier",
                ]
            )

        hist = self._history
        if future_drivers is None:
            last = hist.iloc[-1]
            drivers = pd.DataFrame(
                {
                    "date": future_idx,
                    "planted_area": float(last["planted_area"]),
                    "import_volume": float(last["import_volume"]),
                    "inventory": float(last["inventory"]),
                    "weather_index": float(last["weather_index"]),
                    "pest_index": float(last["pest_index"]),
                    "quality_delta": float(last["quality_delta"]),
                    "import_shock": float(last["import_shock"]),
                    "k": float(last["k"]),
                }
            )
        else:
            drivers = self._normalize_frame(future_drivers, require_price=False)
            aligned = drivers.set_index("date").reindex(future_idx).ffill().bfill()
            drivers = aligned.reset_index()
            if "date" not in drivers.columns:
                drivers = drivers.rename(columns={drivers.columns[0]: "date"})
            drivers["date"] = future_idx

        # Concatenate so lag lookups can see pre-horizon plantings/imports.
        combo = pd.concat(
            [
                hist.drop(columns=["price"], errors="ignore"),
                drivers.assign(price=np.nan),
            ],
            ignore_index=True,
        )
        combo = combo.sort_values("date").reset_index(drop=True)
        q_all = self._compute_q(combo, self.config)
        n_hist = len(hist)
        q_future = q_all[n_hist : n_hist + len(future_idx)]

        origin = hist["date"].iloc[0]
        t_future = ((future_idx.year - origin.year) * 12 + (future_idx.month - origin.month)).to_numpy(dtype=float)

        m_flow = np.full(len(future_idx), self._last_m_flow, dtype=float)
        k = drivers["k"].to_numpy(dtype=float)
        p_mech = (m_flow / np.maximum(q_future, self.config.q_floor)) * k
        x = _design_matrix(
            t_future,
            periods=self.config.fourier_periods_months,
            trend_degree=self.config.trend_degree,
        )
        p_resid = x @ self._residual_coef
        price_pred = p_mech + p_resid

        out = pd.DataFrame(
            {
                "date": future_idx,
                "price_pred": price_pred,
                "q": q_future,
                "m_flow": m_flow,
                "p_mechanical": p_mech,
                "p_trend_fourier": p_resid,
            }
        )
        self._forecast_frame = out
        return out

    def backtest(self, test_size: float = 0.2) -> BacktestResult:
        """Chronological hold-out backtest (never random-split).

        Refits on the prefix, predicts the suffix with true drivers (known at
        those dates for inventory/area/imports already observed). Harvest lag
        still prevents using plantings from after the forecast origin for
        near-term supply.
        """
        self._require_fitted()
        assert self._history is not None
        df = self._history
        n = len(df)
        n_test = max(1, int(round(n * float(test_size))))
        n_train = n - n_test
        min_train = max(12, self.config.m_flow_window_months + 3)
        if n_train < min_train:
            raise ValueError(f"train split too small ({n_train} < {min_train})")

        train = df.iloc[:n_train].copy()
        test = df.iloc[n_train:].copy()
        model = CashFlowFourierPredictor(config=self.config)
        model.fit(train)
        pred = model.predict(test["date"], future_drivers=test.drop(columns=["price"]))
        y_true = test["price"].to_numpy(dtype=float)
        y_pred = pred["price_pred"].to_numpy(dtype=float)
        mae, rmse, mape = _metrics(y_true, y_pred)
        return BacktestResult(
            mae=mae,
            rmse=rmse,
            mape=mape,
            n_test=len(y_true),
            y_true=y_true,
            y_pred=y_pred,
            dates=test["date"].to_numpy(),
        )

    def plot_forecast(self, ax: Any | None = None) -> Any:
        """Plot history + last ``predict`` result. Requires matplotlib."""
        self._require_fitted()
        assert self._history is not None
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:  # pragma: no cover
            raise ImportError("matplotlib is required for plot_forecast") from exc

        created_fig = ax is None
        if ax is None:
            _, ax = plt.subplots(figsize=(10, 4))

        hist = self._history
        ax.plot(hist["date"], hist["price"], label="actual", color="black", linewidth=1.5)
        if self._p_mech is not None:
            ax.plot(hist["date"], self._p_mech, label="mechanical M/Q", alpha=0.7)
        if self._forecast_frame is not None:
            fc = self._forecast_frame
            ax.plot(fc["date"], fc["price_pred"], label="forecast", linestyle="--")
        ax.set_xlabel("date")
        ax.set_ylabel("price")
        ax.legend()
        ax.set_title("CashFlowFourierPredictor")
        if created_fig:
            plt.tight_layout()
        return ax

    def fitted_components(self) -> pd.DataFrame:
        """In-sample decomposition for diagnostics."""
        self._require_fitted()
        assert self._history is not None
        assert self._t is not None and self._residual_coef is not None
        assert self._p_mech is not None and self._q_series is not None
        assert self._m_flow_series is not None
        x = _design_matrix(
            self._t,
            periods=self.config.fourier_periods_months,
            trend_degree=self.config.trend_degree,
        )
        resid = x @ self._residual_coef
        return pd.DataFrame(
            {
                "date": self._history["date"].to_numpy(),
                "price": self._history["price"].to_numpy(dtype=float),
                "q": self._q_series,
                "m_flow": self._m_flow_series,
                "p_mechanical": self._p_mech,
                "p_trend_fourier": resid,
                "price_fitted": self._p_mech + resid,
            }
        )

    def _apply_lag_overrides(self, lags: dict[str, float] | None) -> SupplyConfig:
        if not lags:
            return self.config
        forbidden = {"garlic", "chili", "onion", "tỏi", "ớt", "hành"}
        bad = forbidden.intersection({str(k).lower() for k in lags})
        if bad:
            raise ValueError(
                f"commodity-named lag keys {sorted(bad)} are not allowed; "
                "use harvest_months / import_months (or set SupplyConfig from the YAML profile)"
            )
        updates: dict[str, float] = {}
        if "harvest_months" in lags:
            updates["harvest_lag_months"] = float(lags["harvest_months"])
        if "import_months" in lags:
            updates["import_lag_months"] = float(lags["import_months"])
        # Also accept the explicit config field names.
        if "harvest_lag_months" in lags:
            updates["harvest_lag_months"] = float(lags["harvest_lag_months"])
        if "import_lag_months" in lags:
            updates["import_lag_months"] = float(lags["import_lag_months"])
        return replace(self.config, **updates) if updates else self.config

    def _normalize_frame(self, df: pd.DataFrame, *, require_price: bool = True) -> pd.DataFrame:
        if df is None or df.empty:
            raise ValueError("historical_df is empty")
        out = df.copy()
        if "date" not in out.columns:
            raise ValueError("DataFrame must include a 'date' column")
        needed = list(REQUIRED_COLUMNS) if require_price else [c for c in REQUIRED_COLUMNS if c != "price"]
        missing = [c for c in needed if c not in out.columns]
        if missing:
            raise ValueError(f"missing required columns: {missing}")
        out["date"] = pd.to_datetime(out["date"])
        for col, default in OPTIONAL_DEFAULTS.items():
            if col not in out.columns:
                out[col] = self.config.default_k if col == "k" else default
            else:
                out[col] = out[col].fillna(default if col != "k" else self.config.default_k)
        out = out.sort_values("date").reset_index(drop=True)
        return out

    def _compute_q(self, df: pd.DataFrame, cfg: SupplyConfig) -> np.ndarray:
        area = df["planted_area"].to_numpy(dtype=float)
        imports = df["import_volume"].to_numpy(dtype=float)
        inventory = df["inventory"].to_numpy(dtype=float)
        weather = df["weather_index"].to_numpy(dtype=float)
        pest = df["pest_index"].to_numpy(dtype=float)
        quality = df["quality_delta"].to_numpy(dtype=float)
        shock = df["import_shock"].to_numpy(dtype=float)

        domestic = (
            _shift_by_months(area, cfg.harvest_lag_months) * cfg.yield_tonnes_per_ha * weather * pest * (1.0 + quality)
        )
        lagged_imports = _shift_by_months(imports, cfg.import_lag_months) * (1.0 + shock)
        gross = inventory + domestic + lagged_imports
        loss = cfg.loss_fraction * np.maximum(gross, 0.0)
        return np.maximum(gross - loss, cfg.q_floor)

    def _require_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("call fit() before predict/backtest/plot")
