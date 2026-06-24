"use client";

import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { useChartTheme } from "@/shared/lib/use-chart-theme";
import { EChart } from "@/shared/ui/echart";

/** Daily price line (gradient area, tooltip). `tone="real"` for ingested prices
 *  (blue), `tone="demo"` for synthetic placeholder data (amber). */
export function PriceChart({
  data,
  labels,
  tone = "demo",
  height = 150,
}: {
  data: number[];
  labels?: string[];
  tone?: "real" | "demo";
  height?: number;
}) {
  const c = useChartTheme();
  const color = tone === "real" ? c["--info"] || "#38bdf8" : c["--demo"] || "#f59e0b";
  const suffix = tone === "demo" ? " (demo)" : "";

  const option = useMemo<EChartsOption>(
    () => ({
      grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: false },
      tooltip: {
        trigger: "axis",
        backgroundColor: c["--surface-2"] || "#1a232e",
        borderColor: c["--border"] || "#243140",
        textStyle: { color: c["--text"] || "#e6edf3", fontSize: 12 },
        valueFormatter: (v) => `${Number(v).toFixed(2)}${suffix}`,
      },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: false,
        data: labels ?? data.map((_, i) => `Phiên ${i + 1}`),
      },
      yAxis: { type: "value", show: false, scale: true },
      series: [
        {
          type: "line",
          data,
          smooth: data.length < 120,
          symbol: "none",
          sampling: "lttb",
          lineStyle: { color, width: 2 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: `${color}55` },
                { offset: 1, color: `${color}00` },
              ],
            },
          },
        },
      ],
    }),
    [data, labels, color, suffix, c],
  );

  return <EChart option={option} height={height} />;
}
