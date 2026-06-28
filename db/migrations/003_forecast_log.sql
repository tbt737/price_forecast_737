-- ============================================================================
-- 003_forecast_log.sql  —  Multi-Commodity Quant Forecasting Platform (Phase ACC-1A)
-- ----------------------------------------------------------------------------
-- Live / shadow forecast-accuracy log. Each row is ONE forecast made on
-- `as_of_date` for a future `target_date`; it is written FIRST (status='pending'),
-- then EVALUATED later — when the actual price for `target_date` becomes available
-- — by filling `actual_price` / errors and flipping status to 'evaluated'.
--
-- This is NOT a backtest table: it records real forward predictions so weekly
-- accuracy can be measured honestly out-of-sample. No accuracy claim is valid
-- until `actual_price` is present (status='evaluated').
--
-- Idempotent (CREATE TABLE/INDEX IF NOT EXISTS); additive; contains NO DROP and
-- does not touch existing tables. NOT applied automatically — apply manually
-- after 002_provenance.sql when the writer phase is approved.
-- ============================================================================

CREATE TABLE IF NOT EXISTS fact_forecast_log (
	forecast_log_id           SERIAL NOT NULL,
	forecast_run_id           VARCHAR(64) NOT NULL,           -- batch id of the forecast run
	commodity_code            VARCHAR(40) NOT NULL,
	as_of_date                DATE NOT NULL,                  -- anchor (last price) date
	target_date               DATE NOT NULL,                  -- predicted business date
	horizon_days              INTEGER NOT NULL,
	model_used                VARCHAR(40) NOT NULL,           -- ridge_ar | gbm | gbm_cyc | ou | naive
	predicted_price           NUMERIC(20, 6) NOT NULL,
	baseline_price            NUMERIC(20, 6) NOT NULL,        -- naive (last-value) reference
	actual_price              NUMERIC(20, 6),                 -- filled at evaluation
	actual_available_at       TIMESTAMP WITH TIME ZONE,
	absolute_error            NUMERIC(20, 6),                 -- |actual - predicted|
	absolute_percentage_error NUMERIC(20, 6),                 -- 100 * |actual - predicted| / actual
	status                    VARCHAR(20) DEFAULT 'pending' NOT NULL,
	metadata_json             JSONB,
	created_at                TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	evaluated_at              TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (forecast_log_id),
	CONSTRAINT ck_forecast_log_predicted_positive CHECK (predicted_price > 0),
	CONSTRAINT ck_forecast_log_horizon            CHECK (horizon_days IN (30, 90)),
	CONSTRAINT ck_forecast_log_target_after_asof  CHECK (target_date > as_of_date),
	CONSTRAINT ck_forecast_log_status             CHECK (status IN ('pending', 'evaluated', 'expired', 'invalid')),
	CONSTRAINT uq_forecast_log_grain UNIQUE (commodity_code, as_of_date, target_date, horizon_days, model_used)
);

-- Pending-evaluation lookup: matured forecasts (target_date passed) awaiting actuals.
CREATE INDEX IF NOT EXISTS ix_forecast_log_pending
	ON fact_forecast_log (target_date)
	WHERE status = 'pending';

-- Per-commodity forecast history.
CREATE INDEX IF NOT EXISTS ix_forecast_log_commodity_asof
	ON fact_forecast_log (commodity_code, as_of_date);

-- Maturity scans by target date.
CREATE INDEX IF NOT EXISTS ix_forecast_log_target_date
	ON fact_forecast_log (target_date);
