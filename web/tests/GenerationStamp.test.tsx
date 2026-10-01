import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GenerationStamp } from "@/components/GenerationStamp";

describe("saved writing provenance", () => {
  it("labels the original writing period independently of current metrics", () => {
    render(<GenerationStamp at="2026-09-10T12:00:00Z" period={{ season: 2026, week: 1 }} />);
    expect(screen.getByText(/2026 season, through week 1/)).toBeTruthy();
    expect(screen.getByText(/Sep 10, 2026/)).toBeTruthy();
  });
  it("does not invent a date for legacy prose", () => {
    render(<GenerationStamp />);
    expect(screen.getByText(/Writing date unavailable/)).toBeTruthy();
  });
});
