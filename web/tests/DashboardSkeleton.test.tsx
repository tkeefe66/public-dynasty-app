import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { DashboardSkeleton } from "../components/DashboardSkeleton";

describe("DashboardSkeleton", () => {
  it("lays the lead out on the same tracks as the live lead — no rail", () => {
    const { container } = render(<DashboardSkeleton />);
    // The 210px/250px right rail is gone from both; a mismatch here is the
    // 40px shift this skeleton exists to prevent.
    expect(container.innerHTML).not.toContain("210px");
    expect(container.innerHTML).not.toContain("250px");
    expect(container.innerHTML).toContain("620px");
  });

  it("reserves the lead's read-the-trade row", () => {
    // The live lead renders a 9px link row below the strip whenever
    // `lead.href` is set (the default offseason/draft path) — ~21px of height
    // that everything below shifts by if the skeleton omits it.
    const { container } = render(<DashboardSkeleton />);
    const measures = container.querySelectorAll('[class*="max-w-[620px]"]');
    expect(measures).toHaveLength(2);
    expect(measures[1].className).toContain("justify-end");
  });
});
