export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function isUrl(v: unknown): v is string {
  return typeof v === "string" && /^https?:\/\//.test(v);
}

export function shortHash(h?: string | null, n = 10): string {
  return h ? `${h.slice(0, n)}…` : "—";
}
