import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Leaderboard } from "../components/Leaderboard";
import { GMRow, LeaderboardResp } from "../lib/types";
import { gmRow, pillar } from "./helpers";

const EMPTY_PILLARS = {
  results: pillar(0, {}), assets: pillar(0, {}),
};

const leaderboard = vi.fn();
vi.mock("../lib/api", () => ({
  leaderboard: (...args: unknown[]) => leaderboard(...args),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

// Leaderboard rows default to a fully-populated (zero-valued) two-pillar
// breakdown rather than the shared factory's bare `{}` — most tests here
// exercise the breakdown UI, so it's the more useful local default. Callers
// that pass an explicit `pillars` override still win (spread order below).
function row(over: Partial<GMRow> & { user_id: string; rank: number }): GMRow {
  return { ...gmRow(over), pillars: EMPTY_PILLARS, ...over };
}

function resp(rows: GMRow[]): LeaderboardResp {
  return { league_id: "L1", scope: "all", rows, generated_at: "2026-01-01T00:00:00Z" };
}

describe("Leaderboard", () => {
  beforeEach(() => {
    leaderboard.mockReset();
    push.mockClear();
  });

  it("renders one row per GM with rank, owner and rating", async () => {
    leaderboard.mockResolvedValue(resp([
      row({ user_id: "alice", rank: 1, rating: 1840,
            owner: { user_id: "alice", owner_name: "Alice" } }),
      row({ user_id: "bob", rank: 2, rating: 1500,
            owner: { user_id: "bob", owner_name: "Bob" } }),
      row({ user_id: "carol", rank: 3, rating: 1160,
            owner: { user_id: "carol", owner_name: "Carol" } }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} />);
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("1840")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("Carol")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /breakdown for/i })).toHaveLength(3);
  });

  it("shows the Franchise letter and links the owner name to their page", async () => {
    leaderboard.mockResolvedValue(resp([
      row({ user_id: "alice", rank: 1, rating: 1840, letter: "A+",
            owner: { user_id: "alice", owner_name: "Alice" } }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} />);
    const link = await screen.findByRole("link", { name: /Alice/i });
    expect(link).toHaveAttribute("href", "/league/L1/owner/alice");
    expect(screen.getByText("A+")).toBeInTheDocument();
  });

  it("shows the right trend glyph per sign", async () => {
    leaderboard.mockResolvedValue(resp([
      row({ user_id: "up", rank: 1, trend: 2 }),
      row({ user_id: "down", rank: 2, trend: -1 }),
      row({ user_id: "flat", rank: 3, trend: 0 }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} />);
    await screen.findByRole("button", { name: /breakdown for up/i });
    expect(screen.getByLabelText(/up 2/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/down 1/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/no change/i)).toBeInTheDocument();
  });

  it("reveals the two-pillar breakdown when a row is tapped", async () => {
    leaderboard.mockResolvedValue(resp([
      row({ user_id: "alice", rank: 1, rating: 1748,
            owner: { user_id: "alice", owner_name: "Alice" },
            pillars: {
              results: pillar(176, { expected_wins: 100, playoff_success: 49 }),
              assets: pillar(72, { roster_value_share: 40, young_core_share: 25 }),
            } }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} />);
    const user = userEvent.setup();
    const toggle = await screen.findByRole("button", { name: /breakdown for alice/i });
    await user.click(toggle);
    expect(await screen.findByText("1500")).toBeInTheDocument();
    // Pillars.
    expect(screen.getByText("Results")).toBeInTheDocument();
    expect(screen.getByText("Assets")).toBeInTheDocument();
    expect(screen.getByText(/\+176/)).toBeInTheDocument();   // results contribution
    // Signals.
    expect(screen.getByText("Expected Wins")).toBeInTheDocument();
    expect(screen.getByText(/\+100/)).toBeInTheDocument();
    expect(screen.getByText("Roster Value")).toBeInTheDocument();
    expect(screen.getByText(/\+40/)).toBeInTheDocument();
  });

  it("explains how the Franchise Rating works on demand", async () => {
    leaderboard.mockResolvedValue(resp([
      row({ user_id: "alice", rank: 1,
            owner: { user_id: "alice", owner_name: "Alice" } }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} />);
    const toggle = await screen.findByRole("button", {
      name: /how the franchise rating works/i,
    });
    // Collapsed by default.
    expect(screen.queryByText(/an exactly average GM/i)).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(toggle);
    expect(await screen.findByText(/an exactly average GM/i)).toBeInTheDocument();
    expect(screen.getByText(/two pillars/i)).toBeInTheDocument();
    expect(screen.getByText(/roster value share, young-core share, draft capital/i)).toBeInTheDocument();
  });

  it("renders an empty state when there are no GMs", async () => {
    leaderboard.mockResolvedValue(resp([]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} />);
    expect(await screen.findByText(/no completed season/i)).toBeInTheDocument();
  });

  /* Under v2 NO weight tree carries an `outlook` pillar key at all (Franchise
   * Rating v2 dropped it from the row shape entirely), so `"outlook" in
   * r.pillars` is permanently false — every league, dynasty included, would
   * read as redraft. Format must come from the league's own capabilities,
   * not be inferred from which pillar keys happen to be present on a row. */
  it("detects redraft from the capabilities format, not a missing pillar", async () => {
    leaderboard.mockResolvedValue(resp([
      row({
        user_id: "alice", rank: 1, model: "v2_dynasty",
        owner: { user_id: "alice", owner_name: "Alice" },
        // v2 dynasty shape: results + assets — exactly what every non-redraft
        // row looks like (dynasty or keeper alike).
        pillars: { results: pillar(100, {}), assets: pillar(50, {}) },
      }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} format="dynasty" />);
    const toggle = await screen.findByRole("button", { name: /how the franchise rating works/i });
    await userEvent.setup().click(toggle);
    expect(screen.queryByText(/one pillar/i)).not.toBeInTheDocument();
    expect(screen.getByText(/two pillars/i)).toBeInTheDocument();
  });

  /* Backend wiring landed in api/app/services/leaderboard.py (fix round 1):
   * GMRow now carries roster_rank/roster_of from the same entry.roster_ranks
   * source the standings row reads. Confirms the receipt line the frontend
   * half already had actually fires once real data is present. */
  it("renders the Roster line in the breakdown when the row carries a rank", async () => {
    leaderboard.mockResolvedValue(resp([
      row({
        user_id: "alice", rank: 1,
        owner: { user_id: "alice", owner_name: "Alice" },
        roster_rank: 3, roster_of: 10,
      }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} format="dynasty" />);
    const toggle = await screen.findByRole("button", { name: /breakdown for alice/i });
    await userEvent.setup().click(toggle);
    expect(await screen.findByText("Roster")).toBeInTheDocument();
    expect(screen.getByText("#3 of 10")).toBeInTheDocument();
  });

  it("omits the Roster line when the row carries no rank (redraft, or a pre-feature cache)", async () => {
    leaderboard.mockResolvedValue(resp([
      row({
        user_id: "alice", rank: 1,
        owner: { user_id: "alice", owner_name: "Alice" },
        roster_rank: null, roster_of: null,
      }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} format="redraft" />);
    const toggle = await screen.findByRole("button", { name: /breakdown for alice/i });
    await userEvent.setup().click(toggle);
    await screen.findByText("Base"); // panel is open
    expect(screen.queryByText("Roster")).not.toBeInTheDocument();
  });

  it("still detects redraft when the format says so, even with an outlook-shaped row", async () => {
    leaderboard.mockResolvedValue(resp([
      row({
        user_id: "bob", rank: 1,
        owner: { user_id: "bob", owner_name: "Bob" },
        pillars: EMPTY_PILLARS,
      }),
    ]));
    render(<Leaderboard leagueId="L1" initialYear="all" seasons={[2024]} format="redraft" />);
    const toggle = await screen.findByRole("button", { name: /how the franchise rating works/i });
    await userEvent.setup().click(toggle);
    expect(screen.getByText(/one pillar/i)).toBeInTheDocument();
  });
});
