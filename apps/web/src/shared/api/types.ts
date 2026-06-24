/** Response shapes mirrored from the FastAPI read-only API (Pydantic models). */

export interface Health {
  status: string;
  version: string;
}

export interface Ready {
  status: string;
  database: string;
}

export interface Stats {
  commodities: number;
  profiles: number;
  instruments: number;
  regions: number;
  data_sources: number;
  fact_rows: number;
}

export interface Commodity {
  commodity_code: string;
  commodity_name: string;
  commodity_group: string;
  base_unit: string;
  default_currency: string;
  notes?: string | null;
}

export interface Instrument {
  instrument_code: string;
  exchange?: string | null;
  symbol?: string | null;
  contract_unit?: string | null;
  currency?: string | null;
}

export interface CommodityDetail extends Commodity {
  instruments: Instrument[];
}

export interface ProfileRegistry {
  commodity_code: string;
  version: number;
  checksum?: string | null;
  source_path?: string | null;
}

export interface ProfileDetail extends ProfileRegistry {
  profile: Record<string, unknown>;
}

export interface PricePoint {
  date: string;
  value: number;
}

export interface PriceSeries {
  commodity_code: string;
  instrument_code?: string | null;
  currency?: string | null;
  points: PricePoint[];
}

export interface ForecastPoint {
  date: string;
  value: number;
  lower: number;
  upper: number;
}

export interface BacktestSummary {
  folds: number;
  mape_pct: number | null;
  naive_mape_pct: number | null;
  beats_naive: boolean;
  candidates?: Record<string, number>;
}

export interface HorizonForecast {
  model_used?: string;
  points: ForecastPoint[];
  backtest: BacktestSummary;
}

export interface Forecast {
  available: boolean;
  reason?: string;
  commodity_code: string;
  instrument_code?: string | null;
  currency?: string | null;
  model?: string;
  last_date?: string;
  last_price?: number;
  horizons?: Record<string, HorizonForecast>;
}
