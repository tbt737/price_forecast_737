-- ============================================================================
-- 001_core_schema.sql  —  Multi-Commodity Quant Forecasting Platform (Phase 2)
-- ----------------------------------------------------------------------------
-- PostgreSQL DDL mirror of the SQLAlchemy ORM models (apps/api/app/models/) and
-- the Alembic migration apps/api/app/migrations/versions/0001_core_star_schema.py.
--
-- GENERATED from the ORM metadata (PostgreSQL dialect) so it cannot drift from
-- the models. Idempotent (CREATE TABLE/INDEX IF NOT EXISTS); contains NO
-- destructive DROP. Apply via Alembic in normal workflows; this raw SQL is for
-- direct provisioning / review.
-- ============================================================================


CREATE TABLE IF NOT EXISTS dim_commodity (
	commodity_key SERIAL NOT NULL,
	commodity_code VARCHAR(40) NOT NULL,
	commodity_name VARCHAR(120) NOT NULL,
	commodity_group VARCHAR(20) NOT NULL,
	base_unit VARCHAR(40) NOT NULL,
	default_currency VARCHAR(10) NOT NULL,
	notes TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (commodity_key),
	UNIQUE (commodity_code)
);


CREATE TABLE IF NOT EXISTS dim_data_source (
	data_source_key SERIAL NOT NULL,
	source_code VARCHAR(60) NOT NULL,
	name VARCHAR(200) NOT NULL,
	url VARCHAR(300),
	access VARCHAR(40),
	license VARCHAR(120),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (data_source_key),
	UNIQUE (source_code)
);


CREATE TABLE IF NOT EXISTS dim_region (
	region_key SERIAL NOT NULL,
	region_code VARCHAR(60) NOT NULL,
	region_name VARCHAR(160) NOT NULL,
	country VARCHAR(60),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (region_key),
	UNIQUE (region_code)
);


CREATE TABLE IF NOT EXISTS commodity_profile_registry (
	registry_id SERIAL NOT NULL,
	commodity_key INTEGER NOT NULL,
	commodity_code VARCHAR(40) NOT NULL,
	source_path VARCHAR(300),
	checksum VARCHAR(64),
	version INTEGER DEFAULT '1' NOT NULL,
	profile JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (registry_id),
	UNIQUE (commodity_key),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE,
	UNIQUE (commodity_code)
);


CREATE TABLE IF NOT EXISTS commodity_region_map (
	map_id SERIAL NOT NULL,
	commodity_key INTEGER NOT NULL,
	region_key INTEGER NOT NULL,
	role VARCHAR(20) NOT NULL,
	label VARCHAR(200),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (map_id),
	CONSTRAINT uq_commodity_region_map UNIQUE (commodity_key, region_key, role),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE,
	FOREIGN KEY(region_key) REFERENCES dim_region (region_key) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS dim_market_instrument (
	market_instrument_key SERIAL NOT NULL,
	commodity_key INTEGER NOT NULL,
	instrument_code VARCHAR(60) NOT NULL,
	exchange VARCHAR(120),
	symbol VARCHAR(40),
	description TEXT,
	contract_unit VARCHAR(60),
	currency VARCHAR(10),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (market_instrument_key),
	CONSTRAINT uq_dim_market_instrument_commodity_code UNIQUE (commodity_key, instrument_code),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS fact_event_risk (
	event_id SERIAL NOT NULL,
	commodity_key INTEGER,
	region_key INTEGER,
	data_source_key INTEGER,
	event_date DATE NOT NULL,
	metric_code VARCHAR(80) NOT NULL,
	category VARCHAR(40),
	release_date DATE NOT NULL,
	value NUMERIC(20, 6),
	unit VARCHAR(40),
	revision INTEGER DEFAULT '0' NOT NULL,
	ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (event_id),
	CONSTRAINT ck_fact_event_risk_revision CHECK (revision >= 0),
	CONSTRAINT ck_fact_event_risk_release CHECK (release_date >= event_date),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE,
	FOREIGN KEY(region_key) REFERENCES dim_region (region_key) ON DELETE SET NULL,
	FOREIGN KEY(data_source_key) REFERENCES dim_data_source (data_source_key) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_fact_event_risk_release_date ON fact_event_risk (release_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_event_risk_grain ON fact_event_risk (coalesce(commodity_key, -1), coalesce(region_key, -1), metric_code, event_date, revision);

CREATE TABLE IF NOT EXISTS fact_logistics_periodic (
	logistics_id SERIAL NOT NULL,
	commodity_key INTEGER,
	region_key INTEGER,
	data_source_key INTEGER,
	period_date DATE NOT NULL,
	period_type VARCHAR(12) DEFAULT 'daily' NOT NULL,
	indicator_code VARCHAR(80) NOT NULL,
	release_date DATE NOT NULL,
	value NUMERIC(20, 6),
	unit VARCHAR(40),
	revision INTEGER DEFAULT '0' NOT NULL,
	ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (logistics_id),
	CONSTRAINT ck_fact_logistics_revision CHECK (revision >= 0),
	CONSTRAINT ck_fact_logistics_release CHECK (release_date >= period_date),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE,
	FOREIGN KEY(region_key) REFERENCES dim_region (region_key) ON DELETE SET NULL,
	FOREIGN KEY(data_source_key) REFERENCES dim_data_source (data_source_key) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_fact_logistics_periodic_release_date ON fact_logistics_periodic (release_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_logistics_grain ON fact_logistics_periodic (coalesce(commodity_key, -1), coalesce(region_key, -1), indicator_code, period_date, revision);

CREATE TABLE IF NOT EXISTS fact_macro_daily (
	macro_id SERIAL NOT NULL,
	commodity_key INTEGER,
	data_source_key INTEGER,
	macro_date DATE NOT NULL,
	indicator_code VARCHAR(80) NOT NULL,
	release_date DATE NOT NULL,
	value NUMERIC(20, 6),
	unit VARCHAR(40),
	revision INTEGER DEFAULT '0' NOT NULL,
	ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (macro_id),
	CONSTRAINT ck_fact_macro_daily_revision CHECK (revision >= 0),
	CONSTRAINT ck_fact_macro_daily_release CHECK (release_date >= macro_date),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE,
	FOREIGN KEY(data_source_key) REFERENCES dim_data_source (data_source_key) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_fact_macro_daily_release_date ON fact_macro_daily (release_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_macro_daily_grain ON fact_macro_daily (coalesce(commodity_key, -1), indicator_code, macro_date, revision);

CREATE TABLE IF NOT EXISTS fact_supply_demand_periodic (
	sd_id SERIAL NOT NULL,
	commodity_key INTEGER NOT NULL,
	region_key INTEGER,
	data_source_key INTEGER,
	period_date DATE NOT NULL,
	period_type VARCHAR(12) DEFAULT 'monthly' NOT NULL,
	metric_code VARCHAR(80) NOT NULL,
	release_date DATE NOT NULL,
	value NUMERIC(20, 6),
	unit VARCHAR(40),
	revision INTEGER DEFAULT '0' NOT NULL,
	ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (sd_id),
	CONSTRAINT ck_fact_sd_revision CHECK (revision >= 0),
	CONSTRAINT ck_fact_sd_release CHECK (release_date >= period_date),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE,
	FOREIGN KEY(region_key) REFERENCES dim_region (region_key) ON DELETE SET NULL,
	FOREIGN KEY(data_source_key) REFERENCES dim_data_source (data_source_key) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_fact_supply_demand_periodic_release_date ON fact_supply_demand_periodic (release_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_sd_grain ON fact_supply_demand_periodic (commodity_key, coalesce(region_key, -1), metric_code, period_date, revision);

CREATE TABLE IF NOT EXISTS fact_weather_daily (
	weather_id SERIAL NOT NULL,
	commodity_key INTEGER NOT NULL,
	region_key INTEGER NOT NULL,
	data_source_key INTEGER,
	weather_date DATE NOT NULL,
	metric_code VARCHAR(60) NOT NULL,
	release_date DATE NOT NULL,
	value NUMERIC(20, 6),
	unit VARCHAR(40),
	revision INTEGER DEFAULT '0' NOT NULL,
	ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (weather_id),
	CONSTRAINT ck_fact_weather_daily_revision CHECK (revision >= 0),
	CONSTRAINT ck_fact_weather_daily_release CHECK (release_date >= weather_date),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE,
	FOREIGN KEY(region_key) REFERENCES dim_region (region_key) ON DELETE CASCADE,
	FOREIGN KEY(data_source_key) REFERENCES dim_data_source (data_source_key) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_fact_weather_daily_release_date ON fact_weather_daily (release_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_weather_daily_grain ON fact_weather_daily (commodity_key, region_key, metric_code, weather_date, revision);

CREATE TABLE IF NOT EXISTS fact_price_daily (
	price_id SERIAL NOT NULL,
	commodity_key INTEGER NOT NULL,
	market_instrument_key INTEGER,
	data_source_key INTEGER,
	price_date DATE NOT NULL,
	open NUMERIC(20, 6),
	high NUMERIC(20, 6),
	low NUMERIC(20, 6),
	close NUMERIC(20, 6),
	settle NUMERIC(20, 6),
	volume NUMERIC(20, 2),
	open_interest NUMERIC(20, 2),
	currency VARCHAR(10),
	release_date DATE NOT NULL,
	value NUMERIC(20, 6),
	unit VARCHAR(40),
	revision INTEGER DEFAULT '0' NOT NULL,
	ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (price_id),
	CONSTRAINT ck_fact_price_daily_revision CHECK (revision >= 0),
	CONSTRAINT ck_fact_price_daily_release CHECK (release_date >= price_date),
	FOREIGN KEY(commodity_key) REFERENCES dim_commodity (commodity_key) ON DELETE CASCADE,
	FOREIGN KEY(market_instrument_key) REFERENCES dim_market_instrument (market_instrument_key) ON DELETE SET NULL,
	FOREIGN KEY(data_source_key) REFERENCES dim_data_source (data_source_key) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_fact_price_daily_release_date ON fact_price_daily (release_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_price_daily_grain ON fact_price_daily (commodity_key, coalesce(market_instrument_key, -1), price_date, revision);
