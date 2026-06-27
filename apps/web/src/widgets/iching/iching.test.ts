import { describe, expect, it } from "vitest";
import { castReading, HEX_NAMES, hexagramOf, leanOf, type Line } from "./iching";

const lines = (bits: string): Line[] => bits.split("").map((b) => ({ yang: b === "1", changing: false }));
const seq = (vals: number[]) => {
  let i = 0;
  return () => vals[i++ % vals.length];
};

describe("iching", () => {
  it("has 64 distinct hexagrams", () => {
    expect(Object.keys(HEX_NAMES)).toHaveLength(64);
    expect(new Set(Object.keys(HEX_NAMES)).size).toBe(64);
  });

  it("maps lines to the right hexagram + trigrams", () => {
    const thai = hexagramOf(lines("111000")); // Earth (Khôn) over Heaven (Càn)
    expect(thai.name).toBe("Thái");
    expect(thai.lower.name).toBe("Càn");
    expect(thai.upper.name).toBe("Khôn");
    expect(thai.yangCount).toBe(3);
  });

  it("leans bullish for pure yang, bearish for pure yin", () => {
    expect(leanOf(hexagramOf(lines("111111"))).tone).toBe("up");
    expect(leanOf(hexagramOf(lines("000000"))).tone).toBe("down");
  });

  it("all old-yang cast → Thuần Càn changing into Thuần Khôn", () => {
    const r = castReading(() => 0); // every coin = 3 → sum 9 → lão dương (yang + changing)
    expect(r.primary.name).toBe("Thuần Càn");
    expect(r.changingIndices).toHaveLength(6);
    expect(r.changed?.name).toBe("Thuần Khôn");
    expect(r.primaryLean.tone).toBe("up");
    expect(r.changedLean?.tone).toBe("down");
  });

  it("static cast (sum 8 per line) has no changing lines / biến quẻ", () => {
    const r = castReading(seq([0, 0, 0.9])); // 3+3+2 = 8 → thiếu âm (yin, stable)
    expect(r.changingIndices).toHaveLength(0);
    expect(r.changed).toBeNull();
    expect(r.primary.name).toBe("Thuần Khôn");
  });
});
