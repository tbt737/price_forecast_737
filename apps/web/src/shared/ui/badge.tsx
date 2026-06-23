import type { ReactNode } from "react";
import { cn } from "@/shared/lib/cn";

type Tone = "neutral" | "brand" | "info" | "demo";

const TONES: Record<Tone, string> = {
  neutral: "border-border text-muted",
  brand: "border-brand text-brand",
  info: "border-info text-info",
  demo: "border-demo text-demo",
};

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}
