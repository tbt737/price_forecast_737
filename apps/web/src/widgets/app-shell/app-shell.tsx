import type { ReactNode } from "react";
import { ThemeToggle } from "@/app-layer/theme-toggle";

/** Top-level application shell: sticky header with brand + theme control. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-bg text-text">
      <div aria-hidden className="h-0.5 w-full bg-gradient-to-r from-brand via-info to-demo" />
      <header
        className="sticky top-0 z-20 border-b border-border backdrop-blur"
        style={{ background: "color-mix(in srgb, var(--surface) 88%, transparent)" }}
      >
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-6 py-3">
          <span
            className="grid h-9 w-9 place-items-center rounded-xl text-lg"
            style={{ background: "var(--brand-soft)" }}
            aria-hidden
          >
            🌾
          </span>
          <div className="leading-tight">
            <h1 className="text-sm font-semibold tracking-tight">Multi-Commodity Quant Forecasting</h1>
            <p className="text-xs text-muted">Configuration-driven platform</p>
          </div>
          <nav className="ml-auto flex items-center gap-4">
            <a
              href="/api/docs"
              className="text-xs font-medium text-info hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              API docs
            </a>
            <ThemeToggle />
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
      <footer className="mx-auto max-w-7xl px-6 pb-10 pt-4 text-xs text-subtle">
        Read-only data layer · charts marked DEMO are synthetic · API at{" "}
        <a href="/api/docs" className="text-info hover:underline" target="_blank" rel="noopener noreferrer">
          /api/docs
        </a>
      </footer>
    </div>
  );
}
