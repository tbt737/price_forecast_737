export function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3 text-center">
      <div className="font-mono text-2xl font-bold tabular-nums text-brand">{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}
