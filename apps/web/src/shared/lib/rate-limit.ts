/**
 * Minimal in-memory sliding-window rate limiter (SEC-2). Pure + deterministic: the clock
 * is injectable so it can be unit-tested without real time. Per-instance state (fine for
 * the AI-chat proxy — a distributed limiter is overkill at this scale).
 */
export type Clock = () => number;

export interface RateLimiter {
  /** Returns true if `key` has exceeded `limit` requests within the window (and does NOT
   *  count this call); false when allowed (and records it). */
  isLimited(key: string): boolean;
}

export function createRateLimiter(
  limit: number,
  windowMs: number,
  opts: { now?: Clock; maxKeys?: number } = {},
): RateLimiter {
  const now = opts.now ?? Date.now;
  const maxKeys = opts.maxKeys ?? 5_000;
  const hits = new Map<string, number[]>();

  return {
    isLimited(key: string): boolean {
      const t = now();
      if (hits.size > maxKeys) {
        // opportunistic prune of fully-expired keys so the map can't grow unbounded
        for (const [k, ts] of hits) if (ts.every((x) => t - x >= windowMs)) hits.delete(k);
      }
      const recent = (hits.get(key) ?? []).filter((x) => t - x < windowMs);
      if (recent.length >= limit) {
        hits.set(key, recent);
        return true;
      }
      recent.push(t);
      hits.set(key, recent);
      return false;
    },
  };
}
