import { describe, expect, it } from "vitest";
import { isUrl, shortHash, titleCase } from "@/shared/lib/format";

describe("format helpers", () => {
  it("titleCase converts snake_case", () => {
    expect(titleCase("ending_stocks")).toBe("Ending Stocks");
  });

  it("isUrl detects http(s) urls only", () => {
    expect(isUrl("https://example.com")).toBe(true);
    expect(isUrl("http://x")).toBe(true);
    expect(isUrl("not a url")).toBe(false);
    expect(isUrl(123)).toBe(false);
    expect(isUrl(null)).toBe(false);
  });

  it("shortHash truncates or shows a dash", () => {
    expect(shortHash("abcdef123456", 4)).toBe("abcd…");
    expect(shortHash(null)).toBe("—");
    expect(shortHash(undefined)).toBe("—");
  });
});
