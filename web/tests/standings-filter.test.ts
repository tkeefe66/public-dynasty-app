import { describe, it, expect } from "vitest";
import { applyStandingsState, franchiseSortKey } from "../lib/standings-filter";
import { StandingRow } from "../lib/types";

const ROWS: StandingRow[] = [
  { rank: 1, user_id: "u1", owner: { user_id: "u1", owner_name: "Tom" },  net_ktc: 2755, net_ktc_at_trade: 2400, net_ktc_aged: 2600, production_total: 406.8, production_regular: 350.0, production_playoff: 0, production_toilet: 0, trades: 5, grade: "A" },
  { rank: 2, user_id: "u2", owner: { user_id: "u2", owner_name: "Mike" }, net_ktc: 1120, net_ktc_at_trade: 1000, net_ktc_aged: 1050, production_total: 220.1, production_regular: 180.0, production_playoff: 0, production_toilet: 0, trades: 5, grade: "A−" },
  { rank: 3, user_id: "u3", owner: { user_id: "u3", owner_name: "Jim" },  net_ktc:  210, net_ktc_at_trade:  180, net_ktc_aged:  200, production_total: -40.5, production_regular: -30.0, production_playoff: 0, production_toilet: 0, trades: 4, grade: "B" },
  { rank: 4, user_id: "u4", owner: { user_id: "u4", owner_name: "Sarah" },net_ktc: -1890, net_ktc_at_trade: -1700, net_ktc_aged: -1800, production_total: -420.5, production_regular: -380.0, production_playoff: 0, production_toilet: 0, trades: 4, grade: "D" },
];

describe("applyStandingsState", () => {
  it("labels confirmed careers with the owner name while keeping team labels for unlinked leagues", () => {
    const linked = { ...ROWS[0], owner: { ...ROWS[0].owner, franchise_name: "Alex", team_name: "Zebras" } };
    expect(franchiseSortKey(linked)).toBe("Alex");
    expect(franchiseSortKey({ ...ROWS[1], owner: { ...ROWS[1].owner, team_name: "Bears" } })).toBe("Bears");
    expect(applyStandingsState([linked], { sort: { column: "owner_name", direction: "asc" }, filters: { owner_name: ["alex"] } })).toHaveLength(1);
  });
  it("sort by production_total asc", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "production_total", direction: "asc" }, filters: {},
    });
    expect(out[0].owner.owner_name).toBe("Sarah");
    expect(out[3].owner.owner_name).toBe("Tom");
  });

  it("filters by name substring", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "net_ktc", direction: "desc" },
      filters: { owner_name: ["mi"] },
    });
    expect(out.map((r) => r.owner.owner_name)).toEqual(["Mike", "Jim"]);
  });

  it("filters by numeric range", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "net_ktc", direction: "desc" },
      filters: { net_ktc: [0, null] },
    });
    expect(out.map((r) => r.owner.owner_name)).toEqual(["Tom", "Mike", "Jim"]);
  });

  it("filters by grade pills", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "net_ktc", direction: "desc" },
      filters: { grade: ["A", "B"] },
    });
    expect(out.map((r) => r.owner.owner_name)).toEqual(["Tom", "Mike", "Jim"]);
  });

  it("rank renumbers after sort + filter", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "trades", direction: "desc" },
      filters: { grade: ["B"] },
    });
    expect(out[0].rank).toBe(1);
  });
});
