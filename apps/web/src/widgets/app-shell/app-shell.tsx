import type { ReactNode } from "react";
import { ThemeToggle } from "@/app-layer/theme-toggle";

/** Top-level application shell: sticky header + centered content container. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-bg text-text">
      <header className="sticky top-0 z-10 border-b border-border bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-6 py-3">
          <span className="text-lg" aria-hidden>
            🌾
          </span>
          <div className="leading-tight">
            <h1 className="text-sm font-semibold">Multi-Commodity Quant Forecasting</h1>
            <p className="text-xs text-muted">Configuration-driven platform · web (P0 scaffold)</p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <a
              href="/api/docs"
              className="text-xs text-info hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              API docs
            </a>
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
    </div>
  );
}
