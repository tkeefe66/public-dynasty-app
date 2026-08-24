import { describe, it, expect } from "vitest";
import { fmtDate } from "@/lib/format-date";

describe("fmtDate", () => {
  it("renders YYYY-MM-DD as 'Month D, YYYY'", () => {
    expect(fmtDate("2024-10-11")).toBe("October 11, 2024");
  });

  it("drops the leading zero on single-digit days", () => {
    expect(fmtDate("2025-05-05")).toBe("May 5, 2025");
  });

  it("takes the date part of a full ISO timestamp", () => {
    expect(fmtDate("2026-06-13T14:43:04-06:00")).toBe("June 13, 2026");
  });

  it("returns empty string for null/undefined/empty", () => {
    expect(fmtDate(null)).toBe("");
    expect(fmtDate(undefined)).toBe("");
    expect(fmtDate("")).toBe("");
  });

  it("passes through an unparseable value unchanged", () => {
    expect(fmtDate("Offseason")).toBe("Offseason");
  });
});
