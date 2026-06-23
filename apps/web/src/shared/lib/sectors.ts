/** Sector (commodity_group) visual metadata — color + icon for consistent theming. */

export interface SectorMeta {
  label: string;
  icon: string;
  /** CSS variable token for the sector accent color. */
  color: string;
}

const SECTORS: Record<string, SectorMeta> = {
  agriculture: { label: "Agriculture", icon: "🌱", color: "var(--sector-agriculture)" },
  energy: { label: "Energy", icon: "🛢️", color: "var(--sector-energy)" },
  metal: { label: "Metal", icon: "🪙", color: "var(--sector-metal)" },
};

const FALLBACK: SectorMeta = { label: "Other", icon: "📦", color: "var(--text-subtle)" };

export function sectorMeta(group: string): SectorMeta {
  return SECTORS[group] ?? { ...FALLBACK, label: group };
}
