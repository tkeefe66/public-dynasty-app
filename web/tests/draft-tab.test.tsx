import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OwnerDeepDive } from "@/components/OwnerDeepDive";

function detail(overrides: Record<string, unknown> = {}) {
  return {
    league_id: "lg", user_id: "u1",
    owner: { user_id: "u1", owner_name: "Alice" },
    totals_by_lens: {}, career_arc: [], trades: [],
    draft_picks_by_season: {
      "2026": [{
        player_id: "p1", full_name: "Player One", position: "RB",
        round: 1, slot: 1, picks_in_round: 12, draft_season: 2026,
        acquired_via_trade: false, current_value: 0, lowest_value: 0,
        highest_value: 0, avg_slot_value: 0, production_total: 0,
        production_regular: 0, production_playoff: 0, production_toilet: 0,
        games_started: 0, roster_status: "rostered",
      }],
    },
    ...overrides,
  } as never;
}

describe("owner Draft tab", () => {
  it("renders for a redraft owner with no outlook", () => {
    render(<OwnerDeepDive leagueId="lg" detail={detail({ outlook: null })} />);
    // Tab buttons carry an explicit role="tab" (the full ARIA tabs pattern
    // OwnerDeepDive already uses — see tests/OwnerDeepDive.test.tsx), which
    // overrides the native <button> role, so this queries "tab" rather than
    // "button" to match every other test in that suite.
    expect(screen.getByRole("tab", { name: /draft/i })).toBeTruthy();
  });

  it("is absent when the owner has no drafted picks", () => {
    render(
      <OwnerDeepDive
        leagueId="lg"
        detail={detail({ outlook: null, draft_picks_by_season: {} })}
      />,
    );
    expect(screen.queryByRole("tab", { name: /^draft$/i })).toBeNull();
  });
});
