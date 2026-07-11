import { describe, expect, it } from "vitest";
import { filterByGroup } from "@/shared/lib/filter-group";

const items = [
  { commodity_code: "GOLD", commodity_group: "metal" },
  { commodity_code: "ROBUSTA", commodity_group: "agriculture" },
  { commodity_code: "VCB_VN", commodity_group: "equity" },
  { commodity_code: "FPT_VN", commodity_group: "equity" },
];

describe("filterByGroup", () => {
  it("returns everything when no scope is given", () => {
    expect(filterByGroup(items)).toEqual(items);
    expect(filterByGroup(items, {})).toEqual(items);
  });

  it("keeps only the requested group (stocks page)", () => {
    const out = filterByGroup(items, { group: "equity" });
    expect(out.map((c) => c.commodity_code)).toEqual(["VCB_VN", "FPT_VN"]);
  });

  it("drops the excluded group (home explorer hides equities)", () => {
    const out = filterByGroup(items, { excludeGroup: "equity" });
    expect(out.map((c) => c.commodity_code)).toEqual(["GOLD", "ROBUSTA"]);
  });

  it("applies both group and excludeGroup consistently", () => {
    expect(filterByGroup(items, { group: "equity", excludeGroup: "equity" })).toEqual([]);
  });
});
