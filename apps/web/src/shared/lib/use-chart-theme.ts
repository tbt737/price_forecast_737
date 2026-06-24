"use client";

import { useEffect, useState } from "react";

const VARS = ["--demo", "--brand", "--info", "--text", "--text-muted", "--text-subtle", "--border", "--surface-2"] as const;

export type ChartColors = Record<(typeof VARS)[number], string>;

function read(): ChartColors {
  if (typeof document === "undefined") {
    return Object.fromEntries(VARS.map((v) => [v, ""])) as ChartColors;
  }
  const s = getComputedStyle(document.documentElement);
  return Object.fromEntries(VARS.map((v) => [v, s.getPropertyValue(v).trim()])) as ChartColors;
}

/** Resolved CSS-variable colors for charts; re-reads when the theme changes. */
export function useChartTheme(): ChartColors {
  const [colors, setColors] = useState<ChartColors>(read);
  useEffect(() => {
    const update = () => setColors(read());
    update();
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    return () => {
      mo.disconnect();
      mq.removeEventListener("change", update);
    };
  }, []);
  return colors;
}
