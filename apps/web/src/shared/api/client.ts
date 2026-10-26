import { API_BASE } from "@/shared/config/env";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly path: string,
  ) {
    super(`API ${path} → HTTP ${status}`);
    this.name = "ApiError";
  }
}

const pending = new Map<string, Promise<unknown>>();

/** Share only concurrent default GETs; retain no response after completion. */
export function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  // Custom headers, bodies or cancellation signals must keep their own lifecycle.
  if (init !== undefined) return requestJson<T>(path, init);
  const existing = pending.get(path);
  if (existing) return existing as Promise<T>;
  const task = requestJson<T>(path).finally(() => pending.delete(path));
  pending.set(path, task);
  return task;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T;
}
