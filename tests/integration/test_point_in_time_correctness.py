import pytest
from sqlalchemy import text

from ml.build_pandas_mv import OFFLINE_TABLE, PRODUCTION_MV, build_wide_table_pandas


@pytest.mark.integration
def test_pandas_wide_view_point_in_time(seeded_session):
    """
    Offline Pandas builder enforces Point-in-Time Correctness and must never
    claim the production matview name ``mv_ml_daily_features_wide``.
    """
    db_session = seeded_session
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

    db_session.execute(text("""
        INSERT INTO fact_price_daily (commodity_key, data_source_key, price_date, close, release_date, revision)
        VALUES
        (-999, -999, '2024-01-01', 100, '2024-01-01', 0),
        (-999, -999, '2024-01-02', 110, '2024-01-02', 0)
        ON CONFLICT DO NOTHING
    """))

    db_session.execute(text("""
        INSERT INTO fact_weather_daily
        (weather_id, commodity_key, region_key, data_source_key, weather_date,
         metric_code, value, release_date, revision)
        VALUES
        (-999, -999, -999, -999, '2024-01-01', 'rainfall_mm', 15.5, '2024-01-02', 0)
        ON CONFLICT DO NOTHING
    """))
    db_session.commit()

    assert OFFLINE_TABLE != PRODUCTION_MV
    built = build_wide_table_pandas(session=db_session)
    assert built == OFFLINE_TABLE

    offline_only = db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": OFFLINE_TABLE},
    ).scalar()
    assert offline_only == OFFLINE_TABLE

    result_day1 = db_session.execute(text(f"""
        SELECT rainfall_mm
        FROM {OFFLINE_TABLE}
        WHERE commodity_key = -999 AND as_of_date LIKE '2024-01-01%'
    """)).fetchone()

    assert result_day1 is not None, "Day 1 row should exist"
    assert result_day1.rainfall_mm is None or str(result_day1.rainfall_mm) == "nan", (
        "Leakage detected: Future data was accessible on Day 1"
    )

    result_day2 = db_session.execute(text(f"""
        SELECT rainfall_mm
        FROM {OFFLINE_TABLE}
        WHERE commodity_key = -999 AND as_of_date LIKE '2024-01-02%'
    """)).fetchone()

    assert result_day2 is not None, "Day 2 row should exist"
    assert result_day2.rainfall_mm == 15.5, f"Expected 15.5 on Day 2, got {result_day2.rainfall_mm}"

    dupes = db_session.execute(text(f"""
        SELECT commodity_key, as_of_date, COUNT(*) AS n
        FROM {OFFLINE_TABLE}
        GROUP BY commodity_key, as_of_date
        HAVING COUNT(*) > 1
    """)).fetchall()
    assert dupes == []
