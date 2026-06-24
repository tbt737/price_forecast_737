"use client";

import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { useChartTheme } from "@/shared/lib/use-chart-theme";
import { EChart } from "@/shared/ui/echart";

/** DEMO price series as a smooth gradient area line with tooltip (synthetic data). */
export function PriceChart({ data, height = 150 }: { data: number[]; height?: number }) {
  const c = useChartTheme();
  const color = c["--demo"] || "#f59e0b";

  const option = useMemo<EChartsOption>(
    () => ({
      grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: false },
      tooltip: {
        trigger: "axis",
        backgroundColor: c["--surface-2"] || "#1a232e",
        borderColor: c["--border"] || "#243140",
        textStyle: { color: c["--text"] || "#e6edf3", fontSize: 12 },
        valueFormatter: (v) => `${Number(v).toFixed(1)} (demo)`,
      },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: false,
        data: data.map((_, i) => `Phiên ${i + 1}`),
      },
      yAxis: { type: "value", show: false, scale: true },
      series: [
        {
          type: "line",
          data,
          smooth: true,
          symbol: "none",
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
    [data, color, c],
  );

  return <EChart option={option} height={height} />;
}
