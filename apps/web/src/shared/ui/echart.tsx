"use client";

import { useEffect, useRef } from "react";
import type { ECharts, EChartsOption } from "echarts";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

// Only register what the charts use → much smaller bundle than the full `echarts`.
echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, SVGRenderer]);

/** Thin React wrapper around an ECharts instance (SVG renderer, auto-resize). */
export function EChart({ option, height = 150 }: { option: EChartsOption; height?: number }) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);

  useEffect(() => {
    if (!elRef.current) return;
    const chart = echarts.init(elRef.current, undefined, { renderer: "svg" });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(elRef.current);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  return <div ref={elRef} style={{ width: "100%", height }} />;
}
