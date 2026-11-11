import { describe, expect, it } from "vitest";
import { staleDataNote } from "./stale-note";

describe("stale data note for the chat context", () => {
  it("adds nothing for a current or unannotated forecast", () => {
    expect(staleDataNote({ last_date: "2026-11-10", data_age_days: 1, data_stale: false })).toBe("");
    expect(staleDataNote({ last_date: "2026-11-10" })).toBe("");
  });

  it("names the last date and age when the series has stopped updating", () => {
    const note = staleDataNote({ last_date: "2025-06-30", data_age_days: 499, data_stale: true });
    expect(note).toContain("2025-06-30");
    expect(note).toContain("499 ngày trước");
    expect(note).toContain("KHÔNG phải giá thị trường hiện tại");
  });
});
