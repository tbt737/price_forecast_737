import { fetchJson } from "@/shared/api/client";
import type { Commodity, Health, ProfileRegistry, Ready } from "@/shared/api/types";

/** Typed accessors for the read-only API surface (P0 scope). */
export const api = {
  health: () => fetchJson<Health>("/health"),
  ready: () => fetchJson<Ready>("/ready"),
  listCommodities: () => fetchJson<Commodity[]>("/commodities"),
  listProfiles: () => fetchJson<ProfileRegistry[]>("/profiles"),
};
