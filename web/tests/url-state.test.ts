import { describe, expect, it } from "vitest";
import { encodeDashboardState, decodeDashboardState } from "../lib/url-state";

describe("dashboard URL state", () => {
  it("decode defaults", () => {
    // Mutation: collapse an omitted year into an explicit all-time selection.
    const state = decodeDashboardState(new URLSearchParams(""));
    expect(state.year).toBe("auto");
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
    // Mutation: serialize auto as a numeric/explicit year instead of omitting it.
    const out = encodeDashboardState({
      year: "auto", lens: "ktc",
      sort: { column: "auto", direction: "desc" },
      filters: {},
    });
    expect(out).toBe("");
  });

  it("preserves explicit All while sorting", () => {
    // Mutation: strip year=all when a sort updates the URL.
    const state = decodeDashboardState(new URLSearchParams("year=all"));
    const out = encodeDashboardState({ ...state, sort: { column: "gm_rating", direction: "asc" } });
    expect(out).toBe("year=all&sort=gm_rating.asc");
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
