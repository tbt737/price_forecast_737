import { describe, expect, it } from "vitest";
import { createRateLimiter } from "@/shared/lib/rate-limit";

describe("createRateLimiter", () => {
  it("allows requests up to the limit, blocks the (limit+1)th", () => {
    const now = 1_000;
    const rl = createRateLimiter(3, 60_000, { now: () => now });
    expect(rl.isLimited("a")).toBe(false); // 1
    expect(rl.isLimited("a")).toBe(false); // 2
    expect(rl.isLimited("a")).toBe(false); // 3
    expect(rl.isLimited("a")).toBe(true); // 4th over limit
    expect(rl.isLimited("a")).toBe(true); // still blocked within window
  });

  it("isolates keys — one IP hitting the limit does not affect another", () => {
    const now = 0;
    const rl = createRateLimiter(2, 60_000, { now: () => now });
    expect(rl.isLimited("ip1")).toBe(false);
    expect(rl.isLimited("ip1")).toBe(false);
    expect(rl.isLimited("ip1")).toBe(true); // ip1 exhausted
    expect(rl.isLimited("ip2")).toBe(false); // ip2 unaffected
    expect(rl.isLimited("ip2")).toBe(false);
  });

  it("resets after the window slides past old hits", () => {
    let now = 0;
    const rl = createRateLimiter(2, 1_000, { now: () => now });
    expect(rl.isLimited("a")).toBe(false);
    expect(rl.isLimited("a")).toBe(false);
    expect(rl.isLimited("a")).toBe(true); // over limit at t=0
    now = 1_500; // window (1000ms) has fully passed
    expect(rl.isLimited("a")).toBe(false); // old hits expired → allowed again
  });

  it("does not count a blocked call toward future windows", () => {
    let now = 0;
    const rl = createRateLimiter(1, 1_000, { now: () => now });
    expect(rl.isLimited("a")).toBe(false); // records t=0
    now = 500;
    expect(rl.isLimited("a")).toBe(true); // blocked (1 hit still in window), NOT recorded
    now = 1_100; // only the t=0 hit expires; the blocked call was never recorded
    expect(rl.isLimited("a")).toBe(false);
  });
});
