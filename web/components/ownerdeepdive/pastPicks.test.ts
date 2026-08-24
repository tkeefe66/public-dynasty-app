import { describe, it, expect } from "vitest";
import { flattenAllTime, columnTotals, ALL_TIME } from "./pastPicks";
import type { DraftPickResult } from "@/lib/types";

const mk = (over: Partial<DraftPickResult>): DraftPickResult => ({
  player_id: "x", full_name: "X", position: "WR", round: 1, slot: 1,
  picks_in_round: 12, draft_season: 2025, acquired_via_trade: false,
  current_value: 0, lowest_value: 0, highest_value: 0, avg_slot_value: 0,
  production_total: 0, production_regular: 0, production_playoff: 0,
  production_toilet: 0, games_started: 0, roster_status: "rostered", ...over,
});

describe("pastPicks helpers", () => {
  it("ALL_TIME sentinel", () => {
    expect(ALL_TIME).toBe("all");
  });

  it("flattenAllTime merges seasons and sorts by value delta desc", () => {
    const bySeason = {
      "2024": [mk({ player_id: "a", current_value: 100, avg_slot_value: 90 })], // +10
      "2025": [
        mk({ player_id: "b", current_value: 100, avg_slot_value: 50 }),  // +50
        mk({ player_id: "c", current_value: 100, avg_slot_value: 120 }), // -20
      ],
    };
    const out = flattenAllTime(bySeason);
    expect(out.map((r) => r.player_id)).toEqual(["b", "a", "c"]);
  });

  it("columnTotals sums numeric columns including delta", () => {
    const rows = [
      mk({ current_value: 100, lowest_value: 50, highest_value: 150,
           avg_slot_value: 60, production_total: 200, production_regular: 100,
           production_playoff: 30, production_toilet: 5, games_started: 10 }),
      mk({ current_value: 200, lowest_value: 80, highest_value: 260,
           avg_slot_value: 220, production_total: 50, production_regular: 40,
           production_playoff: 0, production_toilet: 2, games_started: 3 }),
    ];
    const t = columnTotals(rows);
    expect(t.current_value).toBe(300);
    expect(t.lowest_value).toBe(130);
    expect(t.highest_value).toBe(410);
    // deltaSum = (100-60) + (200-220) = 40 + (-20) = 20
    expect(t.deltaSum).toBe(20);
    expect(t.production_total).toBe(250);
    expect(t.production_regular).toBe(140);
    expect(t.production_playoff).toBe(30);
    expect(t.production_toilet).toBe(7);
    expect(t.games_started).toBe(13);
  });
});
