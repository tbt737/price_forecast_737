import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchJson } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("concurrent API requests", () => {
  it("shares concurrent GETs but requests fresh data once they finish", async () => {
    let resolve!: (value: Response) => void;
    const response = new Promise<Response>((done) => { resolve = done; });
    const fetch = vi.fn().mockReturnValue(response);
    vi.stubGlobal("fetch", fetch);
    const a = fetchJson("/test-dedupe");
    const b = fetchJson("/test-dedupe");
    expect(fetch).toHaveBeenCalledTimes(1);
    resolve(new Response(JSON.stringify({ value: 1 })));
    expect(await a).toEqual({ value: 1 });
    expect(await b).toEqual({ value: 1 });
    fetch.mockResolvedValue(new Response(JSON.stringify({ value: 2 })));
    expect(await fetchJson("/test-dedupe")).toEqual({ value: 2 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("does not retain failures or merge requests with explicit options", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    const a = fetchJson("/test-error");
    const b = fetchJson("/test-error");
    const failed = await Promise.allSettled([a, b]);
    expect(failed.every((r) => r.status === "rejected" && r.reason instanceof ApiError)).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockImplementation(async () => new Response("{}"));
    await fetchJson("/test-error");
    await Promise.all([fetchJson("/test-custom", {}), fetchJson("/test-custom", {})]);
    expect(fetch).toHaveBeenCalledTimes(4);
  });
});
