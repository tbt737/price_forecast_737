"""Unit tests for production CommodityPricePredictor (deep-research contract)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.forecast import MIN_HISTORY, select_candidate
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
