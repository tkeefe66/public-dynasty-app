import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { OwnersTab } from "../components/OwnersTab";
import { StandingRow } from "../lib/types";

vi.mock("../lib/api", () => ({
  ownerDetail: vi.fn().mockReturnValue(new Promise(() => {})), // never resolves
}));

/** One standings row, with sensible defaults for every required field. */
function owner(over: Partial<StandingRow> & { user_id: string }): StandingRow {
  return {
    rank: 1,
    owner: { user_id: over.user_id, owner_name: over.user_id },
    net_ktc: 0, net_ktc_at_trade: 0, net_ktc_aged: 0,
    production_total: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
    trades: 0, grade: "B",
    ...over,
  };
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false }));
});

describe("OwnersTab rail letter", () => {
  it("separates former owners and ranks the current list without gaps", () => {
    // Mutation: render historical rows in the current rail / retain global ranks.
    render(<OwnersTab leagueId="L1" profiles={{}} onProfilesChange={() => {}}
      owners={[
        owner({ user_id: "gone", rank: 1, owner: { user_id: "gone", owner_name: "Departed", membership_status: "former", last_active_season: 2023 } }),
        owner({ user_id: "here", rank: 2, owner: { user_id: "here", owner_name: "Present", membership_status: "current" } }),
      ]} />);
    expect(screen.getByText("1 current · 1 former")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Departed/ })).toBeNull();
    expect(within(screen.getByRole("link", { name: /Present/ })).getByText("#1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Former owners/ }));
    expect(screen.getByRole("link", { name: /Departed/ }).getAttribute("href")).toBe("/league/L1/owner/gone");
    expect(screen.getByText("Former owner · last played 2023")).toBeTruthy();
  });
  /* `grade` is the trade-scoped verdict (net Trade Value swing vs peers) —
   * a different question than the Franchise Rating letter, computed from a
   * completely different signal set, and StandingsTable's own trade-grade
   * card carries an explicit comment warning the two must not be conflated
   * ("that grade is the trade-scoped one, NOT the Franchise Rating letter on
   * the card above; they are different verdicts"). `gm_letter ?? grade`
   * rendered them in identical styling, so a missing Franchise letter
   * silently surfaced the trade grade in its place — indistinguishable to
   * the reader. Absence must render as absence. */
  it("never falls back to the trade grade for a missing franchise letter", () => {
    render(
      <OwnersTab
        leagueId="L1"
        owners={[owner({ user_id: "u1", gm_letter: null, grade: "A" })]}
        profiles={{}}
        onProfilesChange={() => {}}
      />,
    );
    expect(screen.queryByText("A")).toBeNull();
    expect(screen.getByTitle("Franchise Rating").textContent).toBe("—");
  });

  it("still shows the franchise letter when it is present", () => {
    render(
      <OwnersTab
        leagueId="L1"
        owners={[owner({ user_id: "u1", gm_letter: "B+", grade: "A" })]}
        profiles={{}}
        onProfilesChange={() => {}}
      />,
    );
    expect(screen.getByText("B+")).toBeTruthy();
    // The trade grade must not also render here — it belongs to Trade Grades.
    expect(screen.queryByText("A")).toBeNull();
  });
});
