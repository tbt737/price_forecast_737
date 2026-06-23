import { sectorMeta } from "@/shared/lib/sectors";

export function SectorChip({ group, withIcon = true }: { group: string; withIcon?: boolean }) {
  const s = sectorMeta(group);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={{ color: s.color, borderColor: s.color, background: "color-mix(in srgb, transparent 88%, " + s.color + ")" }}
    >
      {withIcon ? <span aria-hidden>{s.icon}</span> : null}
      {s.label}
    </span>
  );
}
