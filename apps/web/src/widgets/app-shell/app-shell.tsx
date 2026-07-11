import type { ReactNode } from "react";
import Link from "next/link";
import { ThemeToggle } from "@/app-layer/theme-toggle";
import { FloatingAiChat } from "@/widgets/ai-chat";

/** Top-level application shell: sticky header with brand + theme control. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-bg text-text">
      <div aria-hidden className="h-0.5 w-full bg-gradient-to-r from-brand via-info to-demo" />
      <header
        className="sticky top-0 z-20 border-b border-border backdrop-blur"
        style={{ background: "color-mix(in srgb, var(--surface) 88%, transparent)" }}
      >
        <div className="mx-auto flex max-w-7xl items-center gap-2.5 px-4 py-3 sm:gap-3 sm:px-6">
          <Link href="/" className="flex min-w-0 items-center gap-2.5 sm:gap-3">
            <span
              className="grid h-9 w-9 shrink-0 place-items-center rounded-xl text-lg"
              style={{ background: "var(--brand-soft)" }}
              aria-hidden
            >
              🌾
            </span>
            <div className="min-w-0 leading-tight">
              <h1 className="truncate text-sm font-semibold tracking-tight">
                <span className="sm:hidden">Quant Forecasting</span>
                <span className="hidden sm:inline">Multi-Commodity Quant Forecasting</span>
              </h1>
              <p className="hidden text-xs text-muted sm:block">Configuration-driven platform</p>
            </div>
          </Link>
          <nav className="ml-auto flex shrink-0 items-center gap-3 sm:gap-4">
            <Link href="/stocks" className="text-xs font-medium text-text hover:text-brand">
              📈 Cổ phiếu
            </Link>
            <Link href="/iching" className="text-xs font-medium text-text hover:text-brand">
              🔮 Gieo quẻ
            </Link>
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
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
      <footer className="mx-auto max-w-7xl px-4 pb-10 pt-4 text-xs text-subtle sm:px-6">
        Read-only data layer · charts marked DEMO are synthetic · API at{" "}
        <a href="/api/docs" className="text-info hover:underline" target="_blank" rel="noopener noreferrer">
          /api/docs
        </a>
      </footer>
      <FloatingAiChat />
    </div>
  );
}
