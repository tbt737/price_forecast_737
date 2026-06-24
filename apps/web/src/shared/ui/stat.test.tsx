import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import { Stat } from "@/shared/ui/stat";

describe("Stat", () => {
  it("renders the value and label", () => {
    render(<Stat label="Commodities" value={16} />);
    expect(screen.getByText("16")).toBeInTheDocument();
    expect(screen.getByText("Commodities")).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = render(<Stat label="Regions" value={84} hint="loaded" />);
    expect((await axe(container)).violations).toEqual([]);
  });
});
