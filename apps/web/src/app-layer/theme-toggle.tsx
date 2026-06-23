"use client";

import { useEffect, useState } from "react";

type Mode = "os" | "light" | "dark";
const ORDER: Mode[] = ["os", "light", "dark"];
const LABEL: Record<Mode, string> = { os: "🖥️ OS", light: "☀️ Light", dark: "🌙 Dark" };

function apply(mode: Mode) {
  const el = document.documentElement;
  if (mode === "os") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", mode);
  try {
    localStorage.setItem("theme", mode);
  } catch {
    /* ignore storage errors */
  }
}

/** Cycles OS → Light → Dark. OS (default) follows prefers-color-scheme. */
export function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("os");

  useEffect(() => {
    const stored = (localStorage.getItem("theme") as Mode | null) ?? "os";
    setMode(stored);
  }, []);

  function cycle() {
    const next = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
    setMode(next);
    apply(next);
  }

  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={`Theme: ${mode}. Click to change.`}
      className="rounded-card border border-border bg-surface px-3 py-1.5 text-xs text-muted transition-colors hover:text-text"
    >
      {LABEL[mode]}
    </button>
  );
}

/** Inline, render-blocking snippet that applies a stored theme before paint (no flash). */
export const themeNoFlashScript = `(()=>{try{var m=localStorage.getItem('theme');if(m&&m!=='os')document.documentElement.setAttribute('data-theme',m);}catch(e){}})();`;
