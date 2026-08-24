import { describe, it, expect } from "vitest";
import { seasonWeekLabel } from "@/lib/season-week";

describe("seasonWeekLabel", () => {
  it("labels spring/summer trades as before that year's season", () => {
    expect(seasonWeekLabel("2024-06-14", 1)).toBe("Before 2024 season");
  });
  it("labels December trades as after that year's season", () => {
    expect(seasonWeekLabel("2025-12-20", 1)).toBe("After 2025 season");
  });
  it("labels in-season trades by week", () => {
    expect(seasonWeekLabel("2024-10-06", 5)).toBe("Week 5");
  });
});
