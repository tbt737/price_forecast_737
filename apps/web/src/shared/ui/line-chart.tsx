/** Dependency-free SVG area/line chart (themable via `color`). */
export function LineChart({
  data,
  color = "var(--demo)",
  height = 130,
}: {
  data: number[];
  color?: string;
  height?: number;
}) {
  const W = 320;
  const H = height;
  const p = 10;
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const rng = max - min || 1;
  const x = (i: number) => p + (i * (W - 2 * p)) / (data.length - 1);
  const y = (v: number) => H - p - ((v - min) / rng) * (H - 2 * p);
  const line = data.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(data.length - 1).toFixed(1)} ${H - p} L${x(0).toFixed(1)} ${H - p} Z`;
  const lastX = x(data.length - 1);
  const lastY = y(data[data.length - 1]);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="none" role="img" aria-label="demo price series">
      <path d={area} fill={color} opacity={0.13} />
      <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r={3} fill={color} />
      <text x={p} y={12} fontSize={9} fill="var(--text-subtle)">
        {max.toFixed(0)}
      </text>
      <text x={p} y={H - 3} fontSize={9} fill="var(--text-subtle)">
        {min.toFixed(0)}
      </text>
    </svg>
  );
}
