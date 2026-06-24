import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import { EmptyState } from "@/shared/ui/empty-state";

describe("EmptyState", () => {
  it("renders the title and hint", () => {
    render(<EmptyState title="Nothing here" hint="Try a different search" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("Try a different search")).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = render(<EmptyState title="Empty" />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
