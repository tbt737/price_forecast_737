/** Response shapes mirrored from the FastAPI read-only API (Pydantic models). */

export interface Health {
  status: string;
  version: string;
}

export interface Ready {
  status: string;
  database: string;
}

export interface Commodity {
  commodity_code: string;
  commodity_name: string;
  commodity_group: string;
  base_unit: string;
  default_currency: string;
  notes?: string | null;
}

export interface ProfileRegistry {
  commodity_code: string;
  version: number;
  checksum?: string | null;
  source_path?: string | null;
}
