"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { cn } from "@/shared/lib/cn";

export interface TabItem {
  id: string;
  label: string;
  count?: number;
  content: ReactNode;
}

export function Tabs({ items }: { items: TabItem[] }) {
  const [active, setActive] = useState(items[0]?.id);
  const current = items.find((t) => t.id === active) ?? items[0];

  return (
    <div>
      <div role="tablist" className="flex flex-wrap gap-1 border-b border-border">
        {items.map((t) => {
          const on = t.id === current?.id;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={on}
              onClick={() => setActive(t.id)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                on
                  ? "border-brand text-text"
                  : "border-transparent text-muted hover:text-text",
              )}
            >
              {t.label}
              {typeof t.count === "number" ? (
                <span className="ml-1.5 rounded-full bg-surface-2 px-1.5 text-[11px] tabular-nums text-subtle">
                  {t.count}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="animate-fade-in pt-4">
        {current?.content}
      </div>
    </div>
  );
}
