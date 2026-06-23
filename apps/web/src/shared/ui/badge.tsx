import type { ReactNode } from "react";
import { cn } from "@/shared/lib/cn";

type Tone = "neutral" | "brand" | "info" | "demo" | "pos" | "neg";

const TONES: Record<Tone, string> = {
  neutral: "border-border text-muted",
  brand: "border-brand/40 text-brand bg-brand-soft",
  info: "border-info/40 text-info",
  demo: "border-demo/50 text-demo",
  pos: "border-pos/40 text-pos",
  neg: "border-neg/40 text-neg",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}
