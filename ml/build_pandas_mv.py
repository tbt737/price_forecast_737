"""Offline Pandas wide-panel builder — NOT the production ML feature artifact.

Production canonical name ``mv_ml_daily_features_wide`` is a PostgreSQL
MATERIALIZED VIEW owned by ``db/views`` + ``scripts/refresh_ml_features.py``.
This module writes only to ``offline_ml_daily_features_wide_pandas`` for local
experiments / PIT lab tests. It MUST NEVER rename into the production MV name.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

_ROOT = Path(__file__).resolve().parents[1]
_API = _ROOT / "apps" / "api"
for _p in (_ROOT, _API):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.db.session import get_session_factory  # noqa: E402

#: Offline-only artifact. Forbidden to collide with the production matview name.
OFFLINE_TABLE = "offline_ml_daily_features_wide_pandas"
PRODUCTION_MV = "mv_ml_daily_features_wide"


def build_wide_table_pandas(session=None) -> str:
    """Build/replace the offline pandas wide table. Returns the table name.

    Raises on validation or write failure (callers / ``__main__`` must not swallow).
    """
    db = session if session else get_session_factory()()
    owns_session = session is None
    try:
        bind = db.get_bind()
        if not isinstance(bind, Engine):
            raise RuntimeError("session bind must be a SQLAlchemy Engine")
        print("1. Fetching base time grid...")
        if bind.dialect.name == "sqlite":
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
                   COALESCE((r.profile -> 'features' ->> 'min_train_start_date')::date,
                            MIN(p.price_date), '2000-01-01'::date) as start_date
            FROM dim_commodity c
            LEFT JOIN commodity_profile_registry r ON c.commodity_key = r.commodity_key
            LEFT JOIN fact_price_daily p ON c.commodity_key = p.commodity_key
            GROUP BY c.commodity_key, r.profile
            """
        starts_df = pd.read_sql(query_starts, bind)

        grid_dfs = []
        end_date = pd.Timestamp.today().date()
        for _, row in starts_df.iterrows():
            dates = pd.date_range(start=row["start_date"], end=end_date, freq="D")
            grid_dfs.append(
                pd.DataFrame({"commodity_key": row["commodity_key"], "as_of_date": dates.date})
            )
        grid_df = pd.concat(grid_dfs, ignore_index=True)

        print("2. Fetching metrics...")
        # Single-basis rule: only the LATEST revision per (commodity, instrument).
        q_price = """
        SELECT f.commodity_key, f.price_date as as_of_date,
               'price_close' as metric_code, COALESCE(f.close, f.settle, f.value) as val
        FROM fact_price_daily f
        JOIN (
            SELECT commodity_key, market_instrument_key, MAX(revision) AS max_rev
            FROM fact_price_daily
            GROUP BY commodity_key, market_instrument_key
        ) m ON m.commodity_key = f.commodity_key
           AND m.market_instrument_key = f.market_instrument_key
           AND f.revision = m.max_rev
        """
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
            df = pd.read_sql(q, bind)
            if not df.empty:
                dfs.append(df)

        all_events = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame(
            columns=["commodity_key", "as_of_date", "metric_code", "val"]
        )
        global_events = all_events[all_events["commodity_key"].isna()]
        comm_events = all_events[all_events["commodity_key"].notna()]

        if not global_events.empty:
            bcasted = []
            unique_comms = starts_df["commodity_key"].unique()
            for c in unique_comms:
                temp = global_events.copy()
                temp["commodity_key"] = c
                bcasted.append(temp)
            all_events = pd.concat([comm_events] + bcasted, ignore_index=True)
        else:
            all_events = comm_events

        all_events = all_events.sort_values(
            ["commodity_key", "as_of_date", "metric_code", "val"], kind="mergesort"
        )
        all_events = (
            all_events.groupby(["commodity_key", "as_of_date", "metric_code"])["val"]
            .last()
            .reset_index()
        )

        print("3. Pivoting...")
        if all_events.empty:
            print("WARNING: all_events is empty!")
        pivot_df = all_events.pivot(
            index=["commodity_key", "as_of_date"], columns="metric_code", values="val"
        ).reset_index()

        print("4. Merging with grid and Forward Filling...")
        grid_df["as_of_date"] = pd.to_datetime(grid_df["as_of_date"]).astype("datetime64[ns]")
        pivot_df["as_of_date"] = pd.to_datetime(pivot_df["as_of_date"]).astype("datetime64[ns]")
        final_df = pd.merge(grid_df, pivot_df, on=["commodity_key", "as_of_date"], how="left")
        final_df = final_df.sort_values(["commodity_key", "as_of_date"])

        fill_cols = [c for c in final_df.columns if c not in ["commodity_key", "as_of_date"]]
        if fill_cols:
            final_df[fill_cols] = final_df.groupby("commodity_key")[fill_cols].ffill()

        print(f"5. Writing offline artifact {OFFLINE_TABLE!r} (never {PRODUCTION_MV!r})...")
        timestamp = int(time.time())
        staging_table = f"{OFFLINE_TABLE}_staging_{timestamp}"

        if final_df.empty:
            raise ValueError("Staging validation failed: Wide table is empty.")
        if not {"commodity_key", "as_of_date"}.issubset(final_df.columns):
            raise ValueError("Staging validation failed: Missing grain columns.")
        if final_df.duplicated(subset=["commodity_key", "as_of_date"]).any():
            raise ValueError("Staging validation failed: Duplicate grain rows.")
        if staging_table == PRODUCTION_MV or OFFLINE_TABLE == PRODUCTION_MV:
            raise RuntimeError("Refusing to write offline builder into production MV name")

        final_df.to_sql(staging_table, bind, if_exists="replace", index=False)
        db.execute(
            text(
                f"CREATE UNIQUE INDEX uq_{staging_table} "
                f"ON {staging_table} (commodity_key, as_of_date);"
            )
        )
        db.commit()

        print("6. Swapping offline tables transactionally...")
        with bind.begin() as conn:
            if bind.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('ml_feature_offline_swap'));"))
                # Hard refuse: never rename into / replace the production matview name.
                # (Existence of PRODUCTION_MV is fine — we only write OFFLINE_TABLE.)
                exists = conn.execute(
                    text("SELECT to_regclass(:n)"), {"n": f"public.{OFFLINE_TABLE}"}
                ).scalar()
                if exists:
                    bak = f"{OFFLINE_TABLE}_bak_{timestamp}"
                    conn.execute(text(f'ALTER TABLE "{OFFLINE_TABLE}" RENAME TO "{bak}"'))
                    # Index names do not follow the table rename — free the canonical offline index name.
                    conn.execute(
                        text(
                            f'ALTER INDEX IF EXISTS "uq_{OFFLINE_TABLE}" '
                            f'RENAME TO "uq_{bak}"'
                        )
                    )
                conn.execute(text(f'ALTER TABLE "{staging_table}" RENAME TO "{OFFLINE_TABLE}"'))
                conn.execute(
                    text(
                        f'ALTER INDEX "uq_{staging_table}" '
                        f'RENAME TO "uq_{OFFLINE_TABLE}"'
                    )
                )
            else:
                exists = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
                    ),
                    {"n": OFFLINE_TABLE},
                ).scalar()
                if exists:
                    conn.execute(text(f'DROP TABLE "{OFFLINE_TABLE}"'))
                conn.execute(text(f'ALTER TABLE "{staging_table}" RENAME TO "{OFFLINE_TABLE}"'))

        print(f"Done — offline table {OFFLINE_TABLE}")
        return OFFLINE_TABLE
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    try:
        build_wide_table_pandas()
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1) from None
    raise SystemExit(0)
