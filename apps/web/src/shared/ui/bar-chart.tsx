/** Dependency-free SVG bar chart (themable via `color`). */
export function BarChart({
  items,
  color = "var(--brand)",
  height = 130,
}: {
  items: { label: string; value: number }[];
  color?: string;
  height?: number;
}) {
  const W = 320;
  const H = height;
  const p = 22;
  const n = items.length || 1;
  const max = Math.max(1, ...items.map((i) => i.value));
  const bw = ((W - 2 * p) / n) * 0.55;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="profile composition">
      {items.map((it, i) => {
        const cx = p + (i + 0.5) * ((W - 2 * p) / n);
        const h = (it.value / max) * (H - 2 * p);
        return (
          <g key={it.label}>
            <rect
              x={cx - bw / 2}
              y={H - p - h}
              width={bw}
              height={h}
              rx={3}
              fill={color}
              opacity={0.85}
            />
            <text x={cx} y={H - 6} fontSize={9} textAnchor="middle" fill="var(--text-subtle)">
              {it.label}
            </text>
            <text x={cx} y={H - p - h - 4} fontSize={10} textAnchor="middle" fill="var(--text)" fontWeight={600}>
              {it.value}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
