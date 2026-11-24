"""Unit tests for production CommodityPricePredictor (deep-research contract)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from ml.forecast import MIN_HISTORY, clean_price_points, impute_exog, select_candidate
from ml.predictor import CommodityPricePredictor, InsufficientHistoryError


def _synthetic_price_df(n: int = 320, *, seed: int = 0, start: date = date(2022, 1, 3)) -> pd.DataFrame:
    """Business-day-ish synthetic prices with mild seasonality (no DB)."""
    rng = np.random.default_rng(seed)
    dates: list[date] = []
    cursor = start
    while len(dates) < n:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor += timedelta(days=1)
    t = np.arange(n, dtype=float)
    logp = np.log(100.0) + 0.0002 * t + 0.03 * np.sin(2 * np.pi * t / 252.0) + np.cumsum(rng.normal(0, 0.01, n))
    return pd.DataFrame({"date": dates, "value": np.exp(logp)})


def test_insufficient_history_fail_closed() -> None:
    df = _synthetic_price_df(n=100)
    pred = CommodityPricePredictor(min_history=MIN_HISTORY, enable_gbm=False).fit(df, commodity_code="DEMO")
    result = pred.forecast()
    assert result["available"] is False
    assert "need >=" in result["reason"]
    assert result["commodity_code"] == "DEMO"


def test_strict_insufficient_history_raises() -> None:
    df = _synthetic_price_df(n=50)
    with pytest.raises(InsufficientHistoryError):
        CommodityPricePredictor(min_history=MIN_HISTORY, strict=True, enable_gbm=False).fit(df)


def test_forecast_deterministic_and_contract_shape() -> None:
    df = _synthetic_price_df(n=320, seed=11)
    a = CommodityPricePredictor(horizons=(30,), enable_gbm=False, enable_ou=True).fit(
        df, commodity_code="SYNTH", instrument_code="SYNTH_SPOT", currency="USD"
    )
    b = CommodityPricePredictor(horizons=(30,), enable_gbm=False, enable_ou=True).fit(
        df, commodity_code="SYNTH", instrument_code="SYNTH_SPOT", currency="USD"
    )
    fa = a.forecast()
    fb = b.forecast()
    assert fa == fb
    assert fa["available"] is True
    assert fa["history_points"] == 320
    assert fa["instrument_code"] == "SYNTH_SPOT"
    assert fa["currency"] == "USD"
    assert "30" in fa["horizons"]
    hz = fa["horizons"]["30"]
    assert hz["model_used"] in {"naive", "ridge_ar", "ou", "gbm", "gbm_cyc"}
    assert len(hz["points"]) == 30
    assert {"date", "value", "lower", "upper"} <= set(hz["points"][0])
    assert hz["points"][0]["lower"] <= hz["points"][0]["value"] <= hz["points"][0]["upper"]
    bt = hz["backtest"]
    assert "mape_pct" in bt and "naive_mape_pct" in bt and "candidates" in bt
    assert bt["ou_considered"] is True
    assert bt["beats_naive"] == (hz["model_used"] != "naive")


def test_enable_ou_false_omits_ou_candidate() -> None:
    df = _synthetic_price_df(n=300, seed=3)
    result = (
        CommodityPricePredictor(horizons=(30,), enable_gbm=False, enable_ou=False)
        .fit(df, commodity_code="X")
        .forecast()
    )
    assert result["available"] is True
    cands = result["horizons"]["30"]["backtest"]["candidates"]
    assert "ou" not in cands
    assert result["horizons"]["30"]["backtest"]["ou_considered"] is False


def test_switch_margin_matches_select_candidate_helper() -> None:
    # Class uses the same helper — keep the contract pinned.
    used, mape = select_candidate({"ridge_ar": 9.81}, naive_mape=10.0, margin=0.02)
    assert used == "naive" and mape == 10.0
    used2, mape2 = select_candidate({"ridge_ar": 5.0}, naive_mape=10.0, margin=0.02)
    assert used2 == "ridge_ar" and mape2 == 5.0


def test_to_forecast_log_rows_shape() -> None:
    df = _synthetic_price_df(n=300, seed=5)
    result = (
        CommodityPricePredictor(horizons=(30, 90), enable_gbm=False, enable_ou=True)
        .fit(df, commodity_code="LOG")
        .forecast()
    )
    rows = CommodityPricePredictor.to_forecast_log_rows(result, run_id="r1", run_mode="dry_run")
    assert len(rows) == 2
    assert {r["horizon_days"] for r in rows} == {30, 90}
    assert all(r["status"] == "pending" for r in rows)
    assert all(r["predicted_price"] > 0 for r in rows)
    assert rows[0]["metadata_json"]["source"] == "forecast_commodity"


def test_save_load_roundtrip(tmp_path: Path) -> None:
    df = _synthetic_price_df(n=280, seed=9)
    pred = CommodityPricePredictor(horizons=(30,), enable_gbm=False, enable_ou=False).fit(df, commodity_code="SAVE")
    before = pred.forecast()
    path = pred.save(tmp_path / "pred.pkl")
    loaded = CommodityPricePredictor.load(path)
    after = loaded.forecast()
    assert before == after


def test_forecast_commodity_delegates_to_predictor(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Fake:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def fit_from_session(self, session: object, code: str, **kwargs: object) -> _Fake:
            del session, kwargs
            calls.append(f"fit:{code}")
            return self

        def forecast(self, **kwargs: object) -> dict[str, object]:
            del kwargs
            calls.append("forecast")
            return {"available": True, "commodity_code": "DELEGATED"}

    monkeypatch.setattr("ml.predictor.CommodityPricePredictor", _Fake)
    from ml.forecast import forecast_commodity

    out = forecast_commodity(object(), "gold", horizons=(30,), enable_ou=False)
    assert out["commodity_code"] == "DELEGATED"
    assert calls == ["fit:gold", "forecast"]


def test_non_finite_price_is_dropped_not_fatal() -> None:
    """``+inf`` passes a bare ``v > 0`` check; it must be dropped like NaN / non-positive
    values instead of reaching ``log`` and crashing the candidate pool."""
    df = _synthetic_price_df(n=320, seed=11)
    df.loc[150, "value"] = np.inf
    df.loc[151, "value"] = np.nan
    df.loc[152, "value"] = -5.0
    result = CommodityPricePredictor(horizons=(30,)).fit(df, commodity_code="SYNTH").forecast()
    assert result["available"] is True
    assert result["history_points"] == 317
    assert all(np.isfinite(p["value"]) for p in result["horizons"]["30"]["points"])


def test_clean_price_points_keeps_order_and_finite_positive_only() -> None:
    days = [date(2024, 1, d) for d in range(1, 7)]
    dates, values = clean_price_points(days, [1.5, float("inf"), float("nan"), 0.0, -2.0, 3.0])
    assert dates == [days[0], days[5]]
    assert values == [1.5, 3.0]


def test_infinite_exog_cell_is_treated_as_missing() -> None:
    """A single ``inf`` feature cell must behave exactly like a missing one (causal
    forward-fill), never drop a candidate or raise inside XGBoost."""
    df = _synthetic_price_df(n=320, seed=11)
    exog = pd.DataFrame({"as_of_date": df["date"], "driver": np.linspace(0.0, 1.0, len(df))})
    with_inf, with_nan = exog.copy(), exog.copy()
    with_inf.loc[200, "driver"] = np.inf
    with_nan.loc[200, "driver"] = np.nan

    def run(frame: pd.DataFrame) -> dict[str, Any]:
        return CommodityPricePredictor(horizons=(30,)).fit(df, frame, commodity_code="SYNTH").forecast()

    got = run(with_inf)
    assert got == run(with_nan)
    assert "ridge_ar" in got["horizons"]["30"]["backtest"]["candidates"]


def test_impute_exog_inf_fill_is_point_in_time() -> None:
    """The masked cell is filled from the PAST value only — never a later one."""
    days = [date(2024, 1, d) for d in range(1, 5)]
    frame = pd.DataFrame({"driver": [1.0, -np.inf, np.inf, 9.0]}, index=days)
    assert impute_exog(frame, days)["driver"].tolist() == [1.0, 1.0, 1.0, 9.0]


def test_duplicate_dates_collapse_to_last_row(caplog: pytest.LogCaptureFixture) -> None:
    df = _synthetic_price_df(n=320, seed=11)
    corrected = float(df["value"].iloc[-1]) * 1.01
    stale = df.iloc[[-1]].assign(value=1.0)
    dup = pd.concat([df.iloc[:-1], stale, df.iloc[[-1]].assign(value=corrected)], ignore_index=True)
    with caplog.at_level("WARNING", logger="ml.predictor"):
        result = CommodityPricePredictor(horizons=(30,), enable_gbm=False).fit(dup, commodity_code="SYNTH").forecast()
    assert result["history_points"] == 320
    assert result["last_price"] == round(corrected, 4)
    assert "duplicate date" in caplog.text
