import type { ReactNode } from "react";

export function Stat({
  label,
  value,
  hint,
  accent = "var(--brand)",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  accent?: string;
}) {
  return (
    <div className="group relative overflow-hidden rounded-card border border-border bg-surface px-4 py-3.5 shadow-sm2 transition-shadow hover:shadow-card">
      <span
        aria-hidden
        className="absolute inset-x-0 top-0 h-0.5"
        style={{ background: accent }}
      />
      <div className="font-mono text-[26px] font-bold leading-none tabular-nums" style={{ color: accent }}>
        {value}
      </div>
      <div className="mt-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">{label}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-subtle">{hint}</div> : null}
    </div>
  );
}
