import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(r"d:\AI Project\DỰ BÁO GIÁ CẢ HÀNG NÔNG SẢN\apps\api")))
sys.path.insert(0, str(Path(r"d:\AI Project\DỰ BÁO GIÁ CẢ HÀNG NÔNG SẢN")))

from app.db.session import get_session_factory


def build_wide_table_pandas(session=None):
    db = session if session else get_session_factory()()
    try:
        print("1. Fetching base time grid...")
        if db.bind.dialect.name == 'sqlite':
            query_starts = """
            SELECT c.commodity_key,
                   COALESCE(MIN(p.price_date), '2000-01-01') as start_date
            FROM dim_commodity c
            LEFT JOIN fact_price_daily p ON c.commodity_key = p.commodity_key
            GROUP BY c.commodity_key
            """
        else:
            query_starts = """
            SELECT c.commodity_key,
                   COALESCE(
                       (r.profile -> 'features' ->> 'min_train_start_date')::date,
                       MIN(p.price_date),
                       '2000-01-01'::date
                   ) as start_date
            FROM dim_commodity c
            LEFT JOIN commodity_profile_registry r ON c.commodity_key = r.commodity_key
            LEFT JOIN fact_price_daily p ON c.commodity_key = p.commodity_key
            GROUP BY c.commodity_key, r.profile
            """
        starts_df = pd.read_sql(query_starts, db.bind)

        grid_dfs = []
        end_date = pd.Timestamp.today().date()
        for _, row in starts_df.iterrows():
            dates = pd.date_range(start=row['start_date'], end=end_date, freq='D')
            grid_dfs.append(pd.DataFrame({
                'commodity_key': row['commodity_key'],
                'as_of_date': dates.date
            }))
        grid_df = pd.concat(grid_dfs, ignore_index=True)

        print("2. Fetching metrics...")
        q_price = (
            "SELECT commodity_key, price_date as as_of_date, 'price_close' as metric_code, "
            "COALESCE(close, settle, value) as val FROM fact_price_daily"
        )
        q_weather = (
            "SELECT commodity_key, release_date as as_of_date, metric_code, value as val "
            "FROM fact_weather_daily"
        )
        q_macro = (
            "SELECT commodity_key, release_date as as_of_date, indicator_code as metric_code, "
            "value as val FROM fact_macro_daily"
        )
        q_logistics = (
            "SELECT commodity_key, release_date as as_of_date, indicator_code as metric_code, "
            "value as val FROM fact_logistics_periodic"
        )
        q_sd = (
            "SELECT commodity_key, release_date as as_of_date, metric_code, value as val "
            "FROM fact_supply_demand_periodic"
        )
        q_er = (
            "SELECT commodity_key, release_date as as_of_date, metric_code, value as val "
            "FROM fact_event_risk"
        )

        dfs = []
        for q in [q_price, q_weather, q_macro, q_logistics, q_sd, q_er]:
            df = pd.read_sql(q, db.bind)
            if not df.empty:
                dfs.append(df)

        all_events = pd.concat(dfs, ignore_index=True)
        global_events = all_events[all_events['commodity_key'].isna()]
        comm_events = all_events[all_events['commodity_key'].notna()]

        if not global_events.empty:
            bcasted = []
            unique_comms = starts_df['commodity_key'].unique()
            for c in unique_comms:
                temp = global_events.copy()
                temp['commodity_key'] = c
                bcasted.append(temp)
            all_events = pd.concat([comm_events] + bcasted, ignore_index=True)
        else:
            all_events = comm_events

        all_events = all_events.groupby(['commodity_key', 'as_of_date', 'metric_code'])['val'].last().reset_index()

        print("3. Pivoting...")
        if all_events.empty:
            print("WARNING: all_events is empty!")
        else:
            print("ALL EVENTS SAMPLE:", all_events.head())
        pivot_df = all_events.pivot(
            index=['commodity_key', 'as_of_date'], columns='metric_code', values='val'
        ).reset_index()

        print("4. Merging with grid and Forward Filling...")
        grid_df['as_of_date'] = pd.to_datetime(grid_df['as_of_date']).astype('datetime64[ns]')
        pivot_df['as_of_date'] = pd.to_datetime(pivot_df['as_of_date']).astype('datetime64[ns]')
        final_df = pd.merge(grid_df, pivot_df, on=['commodity_key', 'as_of_date'], how='left')
        final_df = final_df.sort_values(['commodity_key', 'as_of_date'])

        fill_cols = [c for c in final_df.columns if c not in ['commodity_key', 'as_of_date']]
        final_df[fill_cols] = final_df.groupby('commodity_key')[fill_cols].ffill()

        print("5. Writing to staging DB...")
        timestamp = int(time.time())
        staging_table = f"mv_ml_daily_features_wide_staging_{timestamp}"
        backup_table = f"mv_ml_daily_features_wide_backup_{timestamp}"

        # Validation before swap
        if final_df.empty:
            raise ValueError("Staging validation failed: Wide table is empty.")
        if not {'commodity_key', 'as_of_date'}.issubset(final_df.columns):
            raise ValueError("Staging validation failed: Missing grain columns.")
        if final_df.duplicated(subset=['commodity_key', 'as_of_date']).any():
            raise ValueError("Staging validation failed: Duplicate grain rows.")

        final_df.to_sql(staging_table, db.bind, if_exists='replace', index=False)
        db.execute(text(f"CREATE UNIQUE INDEX uq_{staging_table} ON {staging_table} (commodity_key, as_of_date);"))
        db.commit()

        print("6. Swapping tables transactionally...")

        with db.bind.begin() as conn:
            # Acquire Postgres advisory lock
            if db.bind.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('ml_feature_view_swap'));"))

            # Check if production table exists
            try:
                # SQLite safe existence check
                if db.bind.dialect.name == 'postgresql':
                    exists = conn.execute(text("SELECT to_regclass('mv_ml_daily_features_wide');")).scalar()
                else:
                    exists = conn.execute(
                        text(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name='mv_ml_daily_features_wide';"
                        )
                    ).scalar()

                if exists:
                    conn.execute(text(f"ALTER TABLE mv_ml_daily_features_wide RENAME TO {backup_table};"))
            except Exception as e:
                print(f"Backup warning: {e}")

            conn.execute(text(f"ALTER TABLE {staging_table} RENAME TO mv_ml_daily_features_wide;"))

            # SQLite does not support RENAME INDEX
            if db.bind.dialect.name == 'postgresql':
                conn.execute(text(f"ALTER INDEX uq_{staging_table} RENAME TO uq_mv_ml_daily_features_wide;"))

        print("Done!")

    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    build_wide_table_pandas()
