import pytest
from sqlalchemy import text

from ml.forecast import forecast_commodity


@pytest.mark.integration
def test_forecast_commodity_insufficient_history(seeded_session):
    """
    Test that forecasting a commodity with insufficient history handles the
    situation gracefully instead of throwing a 500 error, and returns
    available: false with a clear machine-readable reason.
    """
    db_session = seeded_session

    # 1. Insert a commodity with only 10 days of data (insufficient for MIN_HISTORY=252)
    db_session.execute(text(
        "INSERT INTO dim_commodity "
        "(commodity_key, commodity_code, commodity_name, commodity_group, base_unit, default_currency) "
        "VALUES (-998, 'TEST_SHORT', 'Test Short', 'agriculture', 'kg', 'USD') ON CONFLICT DO NOTHING"
    ))
    db_session.execute(text(
        "INSERT INTO dim_data_source (data_source_key, source_code, name) "
        "VALUES (-998, 'TEST_SRC_2', 'Test Src 2') ON CONFLICT DO NOTHING"
    ))
    db_session.execute(text(
        "INSERT INTO dim_market_instrument (market_instrument_key, commodity_key, instrument_code, exchange) "
        "VALUES (-998, -998, 'INST_SHORT', 'TEST') ON CONFLICT DO NOTHING"
    ))
    db_session.commit()

    # Insert 10 rows
    for i in range(10):
        db_session.execute(text(f"""
            INSERT INTO fact_price_daily
            (commodity_key, data_source_key, market_instrument_key, price_date, close, value, release_date, revision)
            VALUES (-998, -998, -998, '2024-01-{(i+1):02d}', 100 + {i}, 100 + {i}, '2024-01-{(i+1):02d}', 0)
        """))
    db_session.commit()

    # 2. Call the forecast
    result = forecast_commodity(db_session, 'TEST_SHORT')

    # 3. Assertions
    assert result is not None
    assert result.get('available') is False
    assert 'reason' in result
    assert (
        'need >=' in result['reason']
        or 'insufficient_history' in result['reason']
        or 'positive prices' in result['reason']
    )
    assert result.get('commodity_code') == 'TEST_SHORT'
