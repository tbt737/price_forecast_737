"use client";

import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";

// Navigation and profile text can load before the chart renderer. Reserve its
// full height while downloading the library to avoid a layout shift.
const ChartEngine = dynamic(
  () => import("./echart-engine").then((module) => module.EChartEngine),
  { ssr: false, loading: () => <div role="status" className="h-full animate-pulse bg-surface-2" aria-label="Đang tải biểu đồ" /> },
);

export function EChart({ option, height = 150 }: { option: EChartsOption; height?: number }) {
  return <div style={{ width: "100%", height }}><ChartEngine option={option} height={height} /></div>;
}
