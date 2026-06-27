import { describe, expect, it } from "vitest";
import { cycleSummary, hanhOf, monthCycle, relation, yearCanChi } from "./ngu-hanh";

describe("ngu-hanh", () => {
  it("year 2026 = Bính Ngọ (Hỏa Mã)", () => {
    const c = yearCanChi(2026);
    expect(c.can).toBe("Bính");
    expect(c.chi).toBe("Ngọ");
    expect(c.canHanh).toBe("Hỏa");
    expect(c.conGiap).toBe("Ngựa");
  });

  it("commodity → element", () => {
    expect(hanhOf("GOLD")?.hanh).toBe("Kim");
    expect(hanhOf("INDIAN_CHILIES")?.hanh).toBe("Hỏa");
    expect(hanhOf("RICE")?.hanh).toBe("Thổ");
    expect(hanhOf(null)).toBeNull();
  });

  it("relations: sinh favourable, khắc unfavourable", () => {
    expect(relation("Mộc", "Hỏa").rel).toBe("được sinh"); // Mộc sinh Hỏa
    expect(relation("Mộc", "Hỏa").favor).toBeGreaterThan(0);
    expect(relation("Thủy", "Hỏa").rel).toBe("bị khắc"); // Thủy khắc Hỏa
    expect(relation("Thủy", "Hỏa").favor).toBeLessThan(0);
    expect(relation("Kim", "Kim").rel).toBe("đồng hành");
  });

  it("monthCycle covers 12 months + summary", () => {
    const cells = monthCycle("Kim");
    expect(cells).toHaveLength(12);
    expect(cells[0].month).toBe(1);
    expect(typeof cycleSummary("Kim").favorable).toBe("string");
  });
});
