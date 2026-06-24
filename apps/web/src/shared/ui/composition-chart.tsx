"use client";

import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { useChartTheme } from "@/shared/lib/use-chart-theme";
import { EChart } from "@/shared/ui/echart";

/** Real profile-composition counts as labelled bars with tooltip. */
export function CompositionChart({
  items,
  height = 150,
}: {
  items: { label: string; value: number }[];
  height?: number;
}) {
  const c = useChartTheme();
  const color = c["--brand"] || "#10b981";

  const option = useMemo<EChartsOption>(
    () => ({
      grid: { left: 6, right: 6, top: 22, bottom: 22, containLabel: false },
      tooltip: {
        trigger: "item",
        backgroundColor: c["--surface-2"] || "#1a232e",
        borderColor: c["--border"] || "#243140",
        textStyle: { color: c["--text"] || "#e6edf3", fontSize: 12 },
      },
      xAxis: {
        type: "category",
        data: items.map((i) => i.label),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: c["--border"] || "#243140" } },
        axisLabel: { color: c["--text-muted"] || "#9fb0bf", fontSize: 10 },
      },
      yAxis: { type: "value", show: false },
      series: [
        {
          type: "bar",
          data: items.map((i) => i.value),
          barWidth: "46%",
          itemStyle: { color, borderRadius: [4, 4, 0, 0] },
          label: { show: true, position: "top", color: c["--text"] || "#e6edf3", fontSize: 11, fontWeight: "bold" },
        },
      ],
    }),
    [items, color, c],
  );

  return <EChart option={option} height={height} />;
}
