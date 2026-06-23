import type { ReactNode } from "react";
import { isUrl, titleCase } from "@/shared/lib/format";

function Cell({ value }: { value: unknown }) {
  if (isUrl(value)) {
    return (
      <a href={value} target="_blank" rel="noopener noreferrer" className="text-info hover:underline">
        link ↗
      </a>
    );
  }
  if (value == null || value === "") return <span className="text-subtle">—</span>;
  if (typeof value === "object") return <span className="text-subtle">{JSON.stringify(value)}</span>;
  return <>{String(value)}</>;
}

/** Renders an arbitrary profile value: list-of-objects → table, list → chips, object → kv, scalar → text. */
export function RenderValue({ value }: { value: unknown }): ReactNode {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-subtle">—</span>;
    if (typeof value[0] === "object" && value[0] !== null) {
      const cols = [...new Set(value.flatMap((o) => Object.keys(o as object)))];
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase text-muted">
                {cols.map((c) => (
                  <th key={c} className="px-2 py-1.5 font-medium">
                    {titleCase(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {value.map((row, i) => (
                <tr key={i} className="border-b border-border/60 last:border-0 hover:bg-surface-2">
                  {cols.map((c) => (
                    <td key={c} className="px-2 py-1.5 align-top">
                      <Cell value={(row as Record<string, unknown>)[c]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return (
      <div className="flex flex-wrap gap-1.5">
        {value.map((v, i) => (
          <span key={i} className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs">
            {String(v)}
          </span>
        ))}
      </div>
    );
  }

  if (value && typeof value === "object") {
    return (
      <table className="w-full text-sm">
        <tbody>
          {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
            <tr key={k} className="border-b border-border/60 last:border-0">
              <th className="w-1/3 px-2 py-1.5 text-left align-top font-medium text-muted">{titleCase(k)}</th>
              <td className="px-2 py-1.5 align-top">
                <Cell value={v} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return <p className="text-sm leading-relaxed">{String(value)}</p>;
}
