// Shared test-fixture factories used across multiple test files. Keeping
// these in one place avoids near-identical copies drifting apart.
//
// NOTE: this file intentionally has no `.test.` in its name so vitest's
// `include: ["./tests/**/*.test.{ts,tsx}"]` pattern (tests/vitest.config.ts)
// does not pick it up as a test file.
import type { DraftPickResult, GMRow, PillarBreakdown } from "../lib/types";

/** A single rookie-draft pick result, with sensible defaults for every
 *  required field. Superset of what any one test needs — override via
 *  `over`. */
export function pick(over: Partial<DraftPickResult> = {}): DraftPickResult {
  return {
    player_id: "p1", full_name: "Aida", position: "WR", round: 1, slot: 1,
    picks_in_round: 12, draft_season: 2025, acquired_via_trade: false,
    current_value: 5000, lowest_value: 3000, highest_value: 6000,
    avg_slot_value: 4000, production_total: 250, production_started: 150,
    production_regular: 100, production_playoff: 20, production_toilet: 13,
    games_started: 10, roster_status: "rostered",
    // Empty by default — matches the backend contract (unranked/keeper/
    // auction/too-thin-a-cohort-cell picks carry "", never a guess). Tests
    // that need a real verdict override it explicitly.
    verdict: "",
    ...over,
  };
}

/** One leaderboard row. `pillars` defaults to `{}` — callers that need a
 *  fully-populated pillar breakdown (v2: results + assets, or results alone
 *  for redraft) should pass it explicitly (see `pillar()` below). */
export function gmRow(over: Partial<GMRow> & { user_id: string; rank: number }): GMRow {
  return {
    owner: { user_id: over.user_id, owner_name: over.user_id },
    rating: 1500,
    letter: "C",
    pillars: {},
    trend: 0,
    trades: 0,
    net_ktc: 0,
    production_regular: 0,
    production_playoff: 0,
    production_toilet: 0,
    ...over,
  };
}

/** A pillar breakdown with an optional signals map (defaults to none). */
export function pillar(
  contribution: number,
  signals: Record<string, number> = {},
): PillarBreakdown {
  return {
    weight: 0.4, z: 0, contribution,
    signals: Object.fromEntries(
      Object.entries(signals).map(([k, c]) => [k, { raw: 0, z: 0, weight: 0, contribution: c }]),
    ),
  };
}
