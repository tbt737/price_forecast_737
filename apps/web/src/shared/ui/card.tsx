import type { ReactNode } from "react";
import { cn } from "@/shared/lib/cn";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-card border border-border bg-surface", className)}>{children}</div>
  );
}

export function CardHeader({ children }: { children: ReactNode }) {
  return (
    <div className="border-b border-border bg-surface-2 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-muted">
      {children}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("p-4", className)}>{children}</div>;
}
