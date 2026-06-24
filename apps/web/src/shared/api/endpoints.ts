import { fetchJson } from "@/shared/api/client";
import type {
  Commodity,
  CommodityDetail,
  Health,
  PriceSeries,
  ProfileDetail,
  ProfileRegistry,
  Ready,
  Stats,
} from "@/shared/api/types";

/** Typed accessors for the read-only API surface. */
export const api = {
  health: () => fetchJson<Health>("/health"),
  ready: () => fetchJson<Ready>("/ready"),
  stats: () => fetchJson<Stats>("/stats"),
  listCommodities: () => fetchJson<Commodity[]>("/commodities"),
  getCommodity: (code: string) => fetchJson<CommodityDetail>(`/commodities/${code}`),
  getPrices: (code: string, days = 365) =>
    fetchJson<PriceSeries>(`/commodities/${code}/prices?days=${days}`),
  listProfiles: () => fetchJson<ProfileRegistry[]>("/profiles"),
  getProfile: (code: string) => fetchJson<ProfileDetail>(`/profiles/${code}`),
};
