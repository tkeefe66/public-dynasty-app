import { describe, expect, it } from "vitest";
import { encodeDashboardState, decodeDashboardState } from "../lib/url-state";

describe("dashboard URL state", () => {
  it("decode defaults", () => {
    const state = decodeDashboardState(new URLSearchParams(""));
    expect(state.year).toBe("all");
    expect(state.lens).toBe("ktc");
    // "auto" sentinel: the view resolves its own default sort (see StandingsTable).
    expect(state.sort).toEqual({ column: "auto", direction: "desc" });
  });

  it("decode round trip", () => {
    const params = new URLSearchParams(
      "year=2024&lens=production&sort=production_total.asc&filter[grade]=A,B",
    );
    const state = decodeDashboardState(params);
    expect(state.year).toBe(2024);
    expect(state.lens).toBe("production");
    expect(state.sort).toEqual({ column: "production_total", direction: "asc" });
    expect(state.filters.grade).toEqual(["A", "B"]);
  });

  it("decodes legacy production sort column to renamed column", () => {
    const state = decodeDashboardState(new URLSearchParams("sort=net_production.asc"));
    expect(state.sort).toEqual({ column: "production_total", direction: "asc" });
  });

  it("decodes legacy production filter column to renamed column", () => {
    const state = decodeDashboardState(
      new URLSearchParams("filter[net_production_started_playoff][gte]=50"),
    );
    expect(state.filters.production_playoff).toEqual([50, null]);
  });

  it("encode strips defaults", () => {
    const out = encodeDashboardState({
      year: "all", lens: "ktc",
      sort: { column: "auto", direction: "desc" },
      filters: {},
    });
    expect(out).toBe("");
  });

  it("encode keeps non-defaults", () => {
    const out = encodeDashboardState({
      year: 2025, lens: "production",
      sort: { column: "trades", direction: "desc" },
      filters: { grade: ["A"] },
    });
    expect(out).toContain("year=2025");
    expect(out).toContain("lens=production");
    expect(out).toContain("sort=trades.desc");
    expect(out).toContain("filter%5Bgrade%5D=A");
  });
});
