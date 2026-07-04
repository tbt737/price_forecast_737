import pytest
from sqlalchemy import text

from ml.build_pandas_mv import build_wide_table_pandas


@pytest.mark.integration
def test_pandas_wide_view_point_in_time(seeded_session):
    """
    Test that the Pandas MV strictly enforces Point-in-Time Correctness.
    A feature released AFTER the price_date must NOT be visible on that price_date,
    even if the observation date is before the price_date.
    """
    db_session = seeded_session
    # 1. Insert a test commodity and data source
    db_session.execute(text(
        "INSERT INTO dim_commodity "
        "(commodity_key, commodity_code, commodity_name, commodity_group, base_unit, default_currency) "
        "VALUES (-999, 'TEST_PIT', 'Test PIT', 'agriculture', 'kg', 'USD') ON CONFLICT DO NOTHING"
    ))
    db_session.execute(text(
        "INSERT INTO dim_data_source (data_source_key, source_code, name) "
        "VALUES (-999, 'TEST_SRC', 'Test Src') ON CONFLICT DO NOTHING"
    ))
    db_session.execute(text(
        "INSERT INTO dim_region (region_key, region_code, region_name) "
        "VALUES (-999, 'TEST_REG', 'Test Reg') ON CONFLICT DO NOTHING"
    ))
    db_session.commit()

    # 2. Insert fact_price_daily data (our anchor dates)
    # Row 1: observation=2024-01-01
    # Row 2: observation=2024-01-02
    db_session.execute(text("""
        INSERT INTO fact_price_daily (commodity_key, data_source_key, price_date, close, release_date, revision)
        VALUES
        (-999, -999, '2024-01-01', 100, '2024-01-01', 0),
        (-999, -999, '2024-01-02', 110, '2024-01-02', 0)
        ON CONFLICT DO NOTHING
    """))

    # 3. Insert weather feature
    # Observation is 2024-01-01, but it was NOT released until 2024-01-02.
    db_session.execute(text("""
        INSERT INTO fact_weather_daily
        (weather_id, commodity_key, region_key, data_source_key, weather_date,
         metric_code, value, release_date, revision)
        VALUES
        (-999, -999, -999, -999, '2024-01-01', 'rainfall_mm', 15.5, '2024-01-02', 0)
        ON CONFLICT DO NOTHING
    """))
    db_session.commit()

    # 4. Build the wide table using Pandas compiler
    build_wide_table_pandas(session=db_session)

    # 5. Query the view as of 2024-01-01
    # The weather feature was released on 2024-01-02, so it should be NULL/NaN on 2024-01-01
    result_day1 = db_session.execute(text("""
        SELECT rainfall_mm
        FROM mv_ml_daily_features_wide
        WHERE commodity_key = -999 AND as_of_date LIKE '2024-01-01%'
    """)).fetchone()

    assert result_day1 is not None, "Day 1 row should exist"
    assert result_day1.rainfall_mm is None or str(result_day1.rainfall_mm) == 'nan', (
        "Leakage detected: Future data was accessible on Day 1"
    )

    # 6. Query the view as of 2024-01-02
    # The weather feature is now released, so it should be visible!
    result_day2 = db_session.execute(text("""
        SELECT rainfall_mm
        FROM mv_ml_daily_features_wide
        WHERE commodity_key = -999 AND as_of_date LIKE '2024-01-02%'
    """)).fetchone()

    assert result_day2 is not None, "Day 2 row should exist"
    assert result_day2.rainfall_mm == 15.5, f"Expected 15.5 on Day 2, got {result_day2.rainfall_mm}"
