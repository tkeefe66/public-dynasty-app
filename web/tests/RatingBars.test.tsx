import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ContributionRow, fmtPts } from "../components/RatingBars";

describe("RatingBars", () => {
  it("formats points with a sign", () => {
    expect(fmtPts(12)).toBe("+12");
    expect(fmtPts(-5)).toBe("-5");
    expect(fmtPts(0)).toBe("0");
  });

  it("renders a labeled contribution row with its points", () => {
    render(<ContributionRow label="Skill" weight={0.43} points={59} scale={100} />);
    expect(screen.getByText("Skill")).toBeInTheDocument();
    expect(screen.getByText("+59")).toBeInTheDocument();
    expect(screen.getByText("43%")).toBeInTheDocument();
  });
});
