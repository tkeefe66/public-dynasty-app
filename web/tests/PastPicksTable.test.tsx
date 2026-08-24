import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PastPicksTable } from "@/components/ownerdeepdive/PastPicksTable";
import { pick } from "./helpers";

/* The table renders a desktop variant (all thirteen columns on one rule) and a
 * wrapped variant below 1024px, one visible per breakpoint — so every value
 * legitimately appears twice in jsdom. Assertions use getAllByText, the same
 * convention StandingsTable's tests use for its two variants. */
describe("PastPicksTable", () => {
  it("renders every season's picks by default (All-Time)", () => {
    render(<PastPicksTable bySeason={{
      "2024": [pick({ draft_season: 2024, full_name: "Older" })],
      "2025": [pick({ full_name: "Aida" })],
    }} />);
    expect(screen.getAllByText("Aida").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Older").length).toBeGreaterThan(0);
  });

  it("narrows to one class when a season is chosen", () => {
    render(<PastPicksTable bySeason={{
      "2024": [pick({ draft_season: 2024, full_name: "Older" })],
      "2025": [pick({ full_name: "Aida" })],
    }} />);
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(screen.getAllByText("Aida").length).toBeGreaterThan(0);
    expect(screen.queryByText("Older")).not.toBeInTheDocument();
  });

  it("shows +delta for a pick above its round average", () => {
    render(<PastPicksTable bySeason={{ "2025": [pick()] }} />);
    // Both the body row and the totals row render +1,000 (single pick: 5000 - 4000 = 1000)
    const matches = screen.getAllByText("+1,000");
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("labels acquisition as Drafted or Via Trade", () => {
    render(<PastPicksTable bySeason={{
      "2025": [pick({ acquired_via_trade: true })],
    }} />);
    expect(screen.getByText(/via trade/i)).toBeInTheDocument();
  });

  it("renders empty state when no picks", () => {
    render(<PastPicksTable bySeason={{}} />);
    expect(screen.getByText(/no completed drafts/i)).toBeInTheDocument();
  });

  it("renders the status chip for rostered picks", () => {
    render(<PastPicksTable bySeason={{ "2025": [pick()] }} />);
    expect(screen.getAllByText("Rostered").length).toBeGreaterThan(0);
  });

  it("renders the status chip for traded picks", () => {
    render(<PastPicksTable bySeason={{ "2025": [pick({ roster_status: "traded" })] }} />);
    expect(screen.getAllByText("Traded").length).toBeGreaterThan(0);
  });

  it("renders the GS column value", () => {
    render(<PastPicksTable bySeason={{ "2025": [pick({ games_started: 10 })] }} />);
    // "10" appears in the body row and in the totals row
    const matches = screen.getAllByText("10");
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("renders a totals row with a Total label and summed production", () => {
    render(<PastPicksTable bySeason={{
      "2025": [
        pick({ player_id: "p1", production_total: 250 }),
        pick({ player_id: "p2", production_total: 50 }),
      ],
    }} />);
    expect(screen.getAllByText("Total").length).toBeGreaterThan(0);
    expect(screen.getAllByText("300.0").length).toBeGreaterThan(0);
  });

  it("leads the run with All-Time, and opens on it", () => {
    render(<PastPicksTable bySeason={{
      "2024": [pick({ draft_season: 2024, player_id: "p2", full_name: "OldPlayer" })],
      "2025": [pick({ full_name: "NewPlayer" })],
    }} />);
    const labels = screen.getAllByRole("button").map((b) => b.textContent);
    expect(labels[0]).toBe("All-Time");
    expect(labels.slice(0, 3)).toEqual(["All-Time", "2025", "2024"]);
    // ...and it is the selected one, so both classes are on screen.
    expect(screen.getAllByText("NewPlayer").length).toBeGreaterThan(0);
    expect(screen.getAllByText("OldPlayer").length).toBeGreaterThan(0);
  });

  it("rerenders cleanly when the empty-state guard flips (rules-of-hooks regression)", () => {
    // The `active`-season useState must run unconditionally on every render,
    // including the empty-state early return. (The useRef/useState pair that
    // drove the retired frozen column is gone with it.) Flipping between an empty and non-empty `bySeason` across
    // rerenders would previously change the hook count/order and either
    // throw or corrupt state.
    const { rerender } = render(<PastPicksTable bySeason={{}} />);
    expect(screen.getByText(/no completed drafts/i)).toBeInTheDocument();

    // The `active` tab was seeded from the season list at mount time (empty),
    // so it doesn't retroactively track the newly-arrived "2025" season —
    // that's pre-existing tab-selection behavior, not part of this fix.
    // What this assertion guards is the hook-order bug: flipping the guard
    // must render the full table (columns/footer) instead of throwing.
    rerender(<PastPicksTable bySeason={{ "2025": [pick({ full_name: "Aida" })] }} />);
    expect(screen.queryByText(/no completed drafts/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("Total").length).toBeGreaterThan(0);

    // Selecting the season explicitly still surfaces its picks.
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(screen.getAllByText("Aida").length).toBeGreaterThan(0);

    rerender(<PastPicksTable bySeason={{}} />);
    expect(screen.getByText(/no completed drafts/i)).toBeInTheDocument();
  });

  it("shows older season picks after clicking All-Time", () => {
    render(<PastPicksTable bySeason={{
      "2024": [pick({ draft_season: 2024, player_id: "p2", full_name: "OldPlayer" })],
      "2025": [pick({ full_name: "NewPlayer" })],
    }} />);
    fireEvent.click(screen.getByRole("button", { name: "All-Time" }));
    expect(screen.getAllByText("OldPlayer").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NewPlayer").length).toBeGreaterThan(0);
  });

  it("hides the value-arc columns for redraft (no dynasty price history)", () => {
    render(<PastPicksTable format="redraft" bySeason={{
      "2025": [pick({ current_value: 0, lowest_value: 0, highest_value: 0, avg_slot_value: 0 })],
    }} />);
    // Omit, don't blank: no "Current"/"vs Slot" header at all.
    expect(screen.queryByText("Current")).not.toBeInTheDocument();
    expect(screen.queryByText("vs Slot")).not.toBeInTheDocument();
    // Total points still renders (the headline figure falls back to it).
    expect(screen.getAllByText("250.0").length).toBeGreaterThan(0);
  });

  it("hides the value-arc columns for redraft even when the rows carry values", () => {
    // The gate is the league's FORMAT, not a zero-value heuristic. Redraft
    // rows DO carry values — grader_io fetches FantasyCalc's redraft set and
    // most of a class matches — so the old heuristic let the columns render,
    // labelled "Today's dynasty market value" over a Lowest/Highest arc read
    // from a snapshot namespace days old at best.
    render(<PastPicksTable format="redraft" bySeason={{
      "2025": [pick({ current_value: 4200, lowest_value: 3900, highest_value: 4400 })],
    }} />);
    expect(screen.queryByText("Current")).not.toBeInTheDocument();
    expect(screen.queryByText("vs Slot")).not.toBeInTheDocument();
  });

  it("hides the value-arc columns for keeper leagues too", () => {
    render(<PastPicksTable format="keeper" bySeason={{
      "2025": [pick({ current_value: 4200 })],
    }} />);
    expect(screen.queryByText("Current")).not.toBeInTheDocument();
  });

  it("keeps the value-arc columns for dynasty, including an all-zero class", () => {
    // Symmetrically: a dynasty class whose values haven't loaded yet still
    // gets its columns. Absence of data is not absence of the concept.
    render(<PastPicksTable bySeason={{
      "2025": [pick({ current_value: 0 }), pick({ player_id: "p2", current_value: 4200 })],
    }} />);
    expect(screen.getAllByText("Current").length).toBeGreaterThan(0);
  });

  it("links out to the league-wide board for the selected season", () => {
    render(<PastPicksTable leagueId="lg" bySeason={{ "2025": [pick()] }} />);
    // The link belongs to a single class, and All-Time is now the opening
    // view — so choosing the season is what puts it on screen.
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    const link = screen.getByRole("link", { name: /2025 draft board/i });
    expect(link.getAttribute("href")).toBe("/league/lg/draft/2025");
  });

  it("drops the board link on All-Time (no single class to open)", () => {
    render(<PastPicksTable leagueId="lg" bySeason={{ "2025": [pick()] }} />);
    fireEvent.click(screen.getByRole("button", { name: "All-Time" }));
    expect(screen.queryByRole("link", { name: /draft board/i })).toBeNull();
  });

  describe("Start %", () => {
    it("renders the share of Total Points that were started", () => {
      render(<PastPicksTable bySeason={{
        "2025": [pick({ production_total: 200, production_started: 60 })],
      }} />);
      expect(screen.getAllByText("30%").length).toBeGreaterThan(0);
    });

    it("shows an em-dash, never 0%, when Total Points is zero", () => {
      // 0/0 rendered as "0%" reads as a verdict on the pick rather than an
      // absence of data — the gate is on the TOTAL being zero.
      render(<PastPicksTable bySeason={{
        "2025": [pick({ production_total: 0, production_started: 0 })],
      }} />);
      expect(screen.queryByText("0%")).not.toBeInTheDocument();
      expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    });

    it("shows a real 0% when nothing was started but Total Points is nonzero", () => {
      // Pins the gate to the TOTAL, not the started value — the easy way to
      // get this backwards is gating on `started === 0` instead.
      render(<PastPicksTable bySeason={{
        "2025": [pick({ production_total: 100, production_started: 0 })],
      }} />);
      expect(screen.getAllByText("0%").length).toBeGreaterThan(0);
    });
  });

  it("hides the ADP columns when no pick in the season has an adp", () => {
    render(<PastPicksTable bySeason={{ "2025": [pick({ adp: null, adp_delta: null })] }} />);
    expect(screen.queryByText("ADP")).not.toBeInTheDocument();
  });

  it("shows the ADP columns and a null-safe dash for an ungraded pick", () => {
    render(<PastPicksTable bySeason={{
      "2025": [
        pick({ player_id: "p1", adp: 8.5, adp_delta: 3.5 }),
        pick({ player_id: "p2", adp: null, adp_delta: null }),
      ],
    }} />);
    expect(screen.getAllByText("ADP").length).toBeGreaterThan(0);
    expect(screen.getAllByText("8.5").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+3.5").length).toBeGreaterThan(0);
    // The ungraded pick's adp/adp_delta render as "—", never 0.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  describe("Verdict", () => {
    it("renders the verdict", () => {
      render(<PastPicksTable bySeason={{ "2025": [pick({ verdict: "hit" })] }} />);
      expect(screen.getAllByText("Hit").length).toBeGreaterThan(0);
    });

    it("drops the Verdict column entirely when nothing in the class can be judged", () => {
      // A header over a column of dashes is worse than no column. Every
      // pick's default verdict is "" (unranked/keeper/auction/too-thin a
      // cohort cell), so the gate must remove the header outright, not print
      // a blank one.
      render(<PastPicksTable bySeason={{ "2025": [pick()] }} />);
      expect(screen.queryByText("Verdict")).not.toBeInTheDocument();
    });

    it("colours a Hit positive and a Bust negative — never swapped", () => {
      // The word carries the meaning; the colour only restates it
      // (`Status`'s own licence). This is the assertion that catches a
      // meaning-inverting edit — a text-content check alone still passes if
      // Hit and Bust swap colours.
      render(<PastPicksTable bySeason={{ "2025": [
        pick({ player_id: "p1", verdict: "hit" }),
        pick({ player_id: "p2", verdict: "bust" }),
      ] }} />);
      const hit = screen.getAllByText("Hit")[0];
      expect(hit.className).toMatch(/text-pos-strong/);
      const bust = screen.getAllByText("Bust")[0];
      expect(bust.className).toMatch(/text-neg-strong/);
    });

    it("carries the verdict into the mobile reflow, not just the desktop row", () => {
      const { container } = render(
        <PastPicksTable bySeason={{ "2025": [pick({ verdict: "hit" })] }} />,
      );
      // Scoped to the `lg:hidden` wrapped-cells container specifically, so a
      // desktop-only rendering can't satisfy this — mirrors
      // `draft-board.test.tsx`'s use of `container.querySelector` to pin a
      // value to one breakpoint's markup.
      const mobile = container.querySelector(".lg\\:hidden") as HTMLElement;
      expect(mobile).toBeTruthy();
      expect(within(mobile).getAllByText("Hit").length).toBeGreaterThan(0);
    });
  });

  it("marks a keeper pick without altering its roster-status label", () => {
    render(<PastPicksTable bySeason={{ "2025": [pick({ is_keeper: true })] }} />);
    expect(screen.getAllByText("Rostered").length).toBeGreaterThan(0);
    expect(screen.getAllByText("· Keeper").length).toBeGreaterThan(0);
  });

  /* verdictSentence — ported from the old FutureDraftTab.test.tsx (it moved
   * here with PastPicksTable in Task 8's fix round; same wording, same
   * assertions). It summarizes every season, not just the one currently
   * selected, so it must not change when the season tab does. */
  describe("draft-slot verdict sentence", () => {
    it("leads with the actual counts when majority beat their slot", () => {
      render(<PastPicksTable bySeason={{ "2025": [
        pick({ player_id: "a", current_value: 5000, avg_slot_value: 4000 }), // hit
        pick({ player_id: "b", current_value: 5000, avg_slot_value: 4000 }), // hit
        pick({ player_id: "c", current_value: 3000, avg_slot_value: 4000 }), // miss
      ] }} />);
      // No ownerName passed here: falls back to third-person "This owner".
      expect(screen.getByText(/2 of this owner's 3 picks beat their draft slot/i)).toBeInTheDocument();
    });

    it("uses the owner's name in the verdict when provided", () => {
      render(<PastPicksTable ownerName="Mike" bySeason={{ "2025": [
        pick({ player_id: "a", current_value: 5000, avg_slot_value: 4000 }), // hit
        pick({ player_id: "b", current_value: 5000, avg_slot_value: 4000 }), // hit
      ] }} />);
      expect(screen.getByText(/2 of mike's 2 picks beat their draft slot/i)).toBeInTheDocument();
    });

    it("stays put across every season and does not repeat per-season splits", () => {
      // Picks span two seasons; the sentence reads over all of them regardless
      // of which season tab (or All-Time) is currently active.
      const bySeason = {
        "2024": [pick({ player_id: "old", draft_season: 2024, current_value: 5000, avg_slot_value: 4000 })], // hit
        "2025": [
          pick({ player_id: "a", current_value: 5000, avg_slot_value: 4000 }), // hit
          pick({ player_id: "b", current_value: 3000, avg_slot_value: 4000 }), // miss
        ],
      };
      const { rerender } = render(<PastPicksTable bySeason={bySeason} />);
      // Default view is the most recent season (2025), but the sentence tallies all 3 picks.
      expect(screen.getByText(/2 of this owner's 3 picks beat their draft slot/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "2024" }));
      expect(screen.getByText(/2 of this owner's 3 picks beat their draft slot/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "All-Time" }));
      expect(screen.getByText(/2 of this owner's 3 picks beat their draft slot/i)).toBeInTheDocument();

      rerender(<PastPicksTable bySeason={bySeason} />);
      expect(screen.getByText(/2 of this owner's 3 picks beat their draft slot/i)).toBeInTheDocument();
    });
  });
});
