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
