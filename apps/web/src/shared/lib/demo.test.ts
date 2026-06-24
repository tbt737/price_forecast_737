import { describe, expect, it } from "vitest";
import { demoSeries } from "@/shared/lib/demo";

describe("demoSeries", () => {
  it("is deterministic for the same code", () => {
    expect(demoSeries("ROBUSTA")).toEqual(demoSeries("ROBUSTA"));
  });

  it("differs between codes", () => {
    expect(demoSeries("ROBUSTA")).not.toEqual(demoSeries("GOLD"));
  });

  it("returns the requested length, all positive", () => {
    const s = demoSeries("CORN", 32);
    expect(s).toHaveLength(32);
    expect(s.every((v) => v > 0)).toBe(true);
  });
});
