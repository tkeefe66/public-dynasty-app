import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { StageLadder } from "@/components/furniture/StageLadder";
import { WINDOW_STAGES } from "@/lib/window";

describe("StageLadder", () => {
  it("draws all five rungs in the fixed low-to-high order", () => {
    render(<StageLadder stage="Contending" />);
    const cells = screen.getAllByRole("listitem").map((n) => n.textContent);
    expect(cells).toEqual([...WINDOW_STAGES]);
  });

  it("lights exactly one rung", () => {
    const { container } = render(<StageLadder stage="Contending" />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(1);
    expect(screen.getByText("Contending").getAttribute("data-on")).toBe("true");
  });

  it("lights none when the owner is unrated", () => {
    const { container } = render(<StageLadder stage={null} />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(0);
  });

  it("lights none for a stage no producer can emit (a stale blob's word)", () => {
    const { container } = render(<StageLadder stage="Peaking" />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(0);
  });
});
