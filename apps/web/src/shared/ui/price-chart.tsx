"use client";

import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { useChartTheme } from "@/shared/lib/use-chart-theme";
import { EChart } from "@/shared/ui/echart";

export interface ForecastOverlay {
  dates: string[];
  value: number[];
  lower: number[];
  upper: number[];
}

/** Daily price line with an optional dashed forecast + confidence band overlay. */
export function PriceChart({
  data,
  labels,
  tone = "demo",
  forecast,
  height = 150,
  showAxes = false,
}: {
  data: number[];
  labels?: string[];
  tone?: "real" | "demo";
  forecast?: ForecastOverlay;
  height?: number;
  showAxes?: boolean;
}) {
  const c = useChartTheme();
  const color = tone === "real" ? c["--info"] || "#38bdf8" : c["--demo"] || "#f59e0b";
  const fcColor = c["--brand"] || "#10b981";
  const suffix = tone === "demo" ? " (demo)" : "";

  const option = useMemo<EChartsOption>(() => {
    const histLabels = labels ?? data.map((_, i) => `Phiên ${i + 1}`);
    const hasForecast = data.length > 0 && !!forecast && forecast.value.length > 0;
    const h = data.length;
    const nullsH: (number | null)[] = Array(h).fill(null);

    const axis = hasForecast ? [...histLabels, ...forecast.dates] : histLabels;

    const historySeries = {
      type: "line" as const,
      name: "Giá",
      data: hasForecast ? [...data, ...Array<number | null>(forecast.value.length).fill(null)] : data,
      smooth: false,
      symbol: "none" as const,
      sampling: "lttb" as const,
      lineStyle: { color, width: 2 },
      areaStyle: {
        color: {
          type: "linear" as const,
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: `${color}40` },
            { offset: 1, color: `${color}00` },
          ],
        },
      },
    };

    const bandSeries = hasForecast
      ? [
          {
            type: "line" as const,
            data: [...nullsH, ...forecast.lower],
            lineStyle: { opacity: 0 },
            stack: "band",
            symbol: "none" as const,
            silent: true,
            tooltip: { show: false },
          },
          {
            type: "line" as const,
            data: [...nullsH, ...forecast.upper.map((u, i) => u - forecast.lower[i])],
            lineStyle: { opacity: 0 },
            areaStyle: { color: fcColor, opacity: 0.13 },
            stack: "band",
            symbol: "none" as const,
            silent: true,
            tooltip: { show: false },
          },
        ]
      : [];

    const forecastSeries = hasForecast
      ? [
          {
            type: "line" as const,
            name: "Dự báo",
            data: [...Array<number | null>(h - 1).fill(null), data[h - 1], ...forecast.value],
            symbol: "none" as const,
            lineStyle: { color: fcColor, width: 2, type: "dashed" as const },
          },
        ]
      : [];

    return {
      animation: false,
      grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: showAxes },
      tooltip: {
        trigger: "axis",
        backgroundColor: c["--surface-2"] || "#1a232e",
        borderColor: c["--border"] || "#243140",
        textStyle: { color: c["--text"] || "#e6edf3", fontSize: 12 },
        valueFormatter: (v) => (v == null ? "—" : `${Number(v).toFixed(2)}${suffix}`),
      },
      xAxis: {
        type: "category", show: showAxes, boundaryGap: false, data: axis,
        axisLabel: { color: c["--text-muted"] || "#9fb0bf", hideOverlap: true, fontSize: 10 },
        axisLine: { lineStyle: { color: c["--border"] || "#243140" } },
      },
      yAxis: {
        type: "value", show: showAxes, scale: true,
        axisLabel: { color: c["--text-muted"] || "#9fb0bf", fontSize: 10 },
        splitLine: { lineStyle: { color: c["--border"] || "#243140", type: "dashed" } },
      },
      series: [...bandSeries, historySeries, ...forecastSeries],
    };
  }, [data, labels, color, fcColor, suffix, forecast, c, showAxes]);

  return <EChart option={option} height={height} />;
}
