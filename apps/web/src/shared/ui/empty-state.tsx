import type { ReactNode } from "react";

export function EmptyState({
  icon = "📭",
  title,
  hint,
}: {
  icon?: string;
  title: string;
  hint?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <span className="text-3xl" aria-hidden>
        {icon}
      </span>
      <p className="text-sm font-medium">{title}</p>
      {hint ? <p className="max-w-sm text-xs text-subtle">{hint}</p> : null}
    </div>
  );
}
