"""Phase 8B integration: with a real (in-memory) price series, the OU candidate
participates in the forecast pool and the output metadata records it — while the
``enable_ou`` hook removes it cleanly. No production DB, no network.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from ml.forecast import forecast_commodity


def _seed_long_series(session, code: str, key: int, n: int = 420) -> None:
    session.execute(
        text(
            "INSERT INTO dim_commodity (commodity_key, commodity_code, commodity_name, commodity_group,"
            " base_unit, default_currency) VALUES (:k, :c, :c, 'agriculture', 'kg', 'USD') ON CONFLICT DO NOTHING"
        ),
        {"k": key, "c": code},
    )
    session.execute(
        text(
            "INSERT INTO dim_data_source (data_source_key, source_code, name) "
            "VALUES (:k, :s, :s) ON CONFLICT DO NOTHING"
        ),
        {"k": key, "s": f"SRC_{code}"},
    )
    session.execute(
        text(
            "INSERT INTO dim_market_instrument (market_instrument_key, commodity_key, instrument_code, exchange)"
            " VALUES (:k, :k, :i, 'TEST') ON CONFLICT DO NOTHING"
        ),
        {"k": key, "i": f"INST_{code}"},
    )
    session.commit()

    # Deterministic mean-reverting series (AR(1) around a base) so OU is identifiable.
    rng = np.random.default_rng(0)
    base, price, start = 100.0, 100.0, date(2022, 1, 1)
    for i in range(n):
        price = base + 0.85 * (price - base) + float(rng.normal(0, 2.5))
        d = (start + timedelta(days=i)).isoformat()
        session.execute(
            text(
                "INSERT INTO fact_price_daily (commodity_key, data_source_key, market_instrument_key, price_date,"
                " close, value, release_date, revision) VALUES (:k,:k,:k,:d,:v,:v,:d,0)"
            ),
            {"k": key, "d": d, "v": float(max(price, 1.0))},
        )
    session.commit()


def _ensure_feature_view(session) -> None:
    # forecast_commodity reads mv_ml_daily_features_wide for exogenous features; provide a
    # minimal compatible view in SQLite (no exog columns ⇒ empty exog, same as production
    # when the view has no extra features).
    session.execute(
        text(
            "CREATE VIEW IF NOT EXISTS mv_ml_daily_features_wide AS "
            "SELECT commodity_key, price_date AS as_of_date, value AS price_close FROM fact_price_daily"
        )
    )
    session.commit()


def test_ou_in_pool_metadata_and_disable_hook(seeded_session) -> None:
    _ensure_feature_view(seeded_session)
    _seed_long_series(seeded_session, "OU_TEST", -990)

    enabled = forecast_commodity(seeded_session, "OU_TEST", horizons=(30,))
    assert enabled["available"] is True
    bt = enabled["horizons"]["30"]["backtest"]
    assert bt["ou_considered"] is True
    assert "ou" in bt["candidates"]  # OU participated in the pool
    # naive benchmark + margin metadata still present and intact
    assert "naive_mape_pct" in bt and "beats_naive" in bt

    disabled = forecast_commodity(seeded_session, "OU_TEST", horizons=(30,), enable_ou=False)
    bt_off = disabled["horizons"]["30"]["backtest"]
    assert bt_off["ou_considered"] is False
    assert "ou" not in bt_off["candidates"]  # cleanly removed by the hook


def test_forecast_pool_is_deterministic(seeded_session) -> None:
    _ensure_feature_view(seeded_session)
    _seed_long_series(seeded_session, "OU_DET", -991)
    a = forecast_commodity(seeded_session, "OU_DET", horizons=(30,))
    b = forecast_commodity(seeded_session, "OU_DET", horizons=(30,))
    assert a["horizons"]["30"]["backtest"]["candidates"] == b["horizons"]["30"]["backtest"]["candidates"]
    assert a["horizons"]["30"]["model_used"] == b["horizons"]["30"]["model_used"]
