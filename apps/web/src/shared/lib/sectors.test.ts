import { describe, expect, it } from "vitest";
import { sectorMeta } from "@/shared/lib/sectors";

describe("sectorMeta", () => {
  it("maps known sectors with a color token", () => {
    expect(sectorMeta("agriculture").label).toBe("Agriculture");
    expect(sectorMeta("energy").color).toContain("--sector-energy");
    expect(sectorMeta("metal").icon).toBeTruthy();
  });

  it("maps the equity sector (VN30 listed shares)", () => {
    const m = sectorMeta("equity");
    expect(m.label).toBe("Cổ phiếu");
    expect(m.color).toContain("--sector-equity");
    expect(m.icon).toBeTruthy();
  });

  it("falls back gracefully for unknown groups", () => {
    const m = sectorMeta("widgets");
    expect(m.label).toBe("widgets");
    expect(m.icon).toBeTruthy();
    expect(m.color).toBeTruthy();
  });
});
