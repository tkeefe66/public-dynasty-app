import { render, screen, within, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { DraftBoard } from "@/components/DraftBoard";

/** The naming-tier caps (`GroupedHead`'s own spanning cells) are ALSO
 *  `role="columnheader"`, sitting in a sibling `role="row"` above the real
 *  label-tier headers. `GroupedHead` is the only thing that stamps
 *  `aria-colspan` on a columnheader, so filtering it out is how these tests
 *  reach only the real, per-column header cells — the ones that carry a
 *  `SortButton` and, for non-identity columns, an `InfoTooltip` trigger. */
function labelHeaders(container: HTMLElement): HTMLElement[] {
  return within(container)
    .getAllByRole("columnheader")
    .filter((h) => !h.hasAttribute("aria-colspan"));
}

function infoTriggers(header: HTMLElement): HTMLElement[] {
  return within(header).queryAllByRole("button", { name: /^info:/ });
}

/** `PickNo`'s round·slot code (`1.01`) is two-tone — the round dim, the slot
 *  in ink — as sibling `<span>`s under one `data-testid="pick-no"` node.
 *  `getByText` only concatenates a node's DIRECT text-child content, so it
 *  never sees the whole code once it's split across nested elements; read
 *  each pick-no node's full `textContent` instead (`StandingsTable.test.tsx`
 *  runs the same workaround for its own two-tone cell). */
function pickNoTexts(container: HTMLElement): string[] {
  return within(container)
    .getAllByTestId("pick-no")
    .map((el) => el.textContent ?? "");
}

const base = {
  league_id: "lg", season: 2026, seasons: [2026], format: "redraft",
  baseline_label: "ADP",
  picks: [{
    player_id: "p1", full_name: "Player One", position: "RB",
    drafter_id: "u1", owner: { user_id: "u1", owner_name: "Alice" },
    round: 1, slot: 1, pick_no: 1, is_keeper: false,
    production_total: 0, baseline: 12, baseline_delta: -11, baseline_source: "sleeper_adp",
    projected_points: 210.5,
  }],
  owners: [{
    user_id: "u1", owner: { user_id: "u1", owner_name: "Alice" },
    adp_total_delta: -11, graded_picks: 1, total_picks: 1,
    production_total: 0,
    hit: 0, average: 0, bust: 0, picks_made: 1,
  }],
};

describe("DraftBoard", () => {
  it("renders picks on draft night with no production column", () => {
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);
    // Renders once in the desktop ledger and once in the ≤700px reflow
    // (StandingsTable/PastPicksTable's own two-variant convention) — never
    // zero, and queryByText below covers the whole tree either way.
    expect(screen.getAllByText("Player One").length).toBeGreaterThan(0);
    expect(screen.queryByText(/total points/i)).toBeNull();
  });

  it("shows production once the class has played", () => {
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: true }} />);
    // Two homes once graded: the picks ledger column and the owners column.
    expect(screen.getAllByText(/total points/i).length).toBeGreaterThan(0);
  });

  it("shows the owners figure it sorts by, once graded", () => {
    // The backend ranks owners by production. Printing only the ADP delta
    // beside that rank puts #1 above #3 on a worse-looking figure and reads
    // as a broken sort.
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true,
          owners: [
            { ...base.owners[0], production_total: 1234.5 },
            {
              user_id: "u2", owner: { user_id: "u2", owner_name: "Bob" },
              adp_total_delta: 40, graded_picks: 1, total_picks: 1,
              production_total: 900,
            },
          ],
        }}
      />,
    );
    const owners = screen.getByRole("table", { name: /draft board owners/i });
    expect(within(owners).getByText("1234.5")).toBeTruthy();
    expect(within(owners).getByText("900.0")).toBeTruthy();
  });

  it("omits the owners section entirely when nothing is gradeable", () => {
    // All-auction class: "results only, no grade". The backend sends no
    // owner rows, and an empty ledger with headers would read as a bug.
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: true, owners: [] }} />);
    expect(screen.queryByRole("table", { name: /draft board owners/i })).toBeNull();
    expect(screen.getAllByText("Player One").length).toBeGreaterThan(0);
  });

  /* INVERTED at the Furniture port. This asserted the season run SCROLLED —
   * the last sanctioned `overflow-x-auto` in the app, kept because losing it
   * made the page body scroll sideways on a phone. The run is a pill-in-a-well
   * now and WRAPS, so the reason expired and the guard's exception list is
   * empty. Same intent — "a long run must not push the page sideways" — met by
   * wrapping rather than by scrolling.
   *
   * Seven seasons is the case that motivated the original exception. */
  it("wraps a long season run rather than scrolling or pushing the page sideways", () => {
    const { container } = render(
      <DraftBoard
        leagueId="lg"
        board={{ ...base, graded: false, seasons: [2026, 2025, 2024, 2023, 2022, 2021, 2020] }}
      />,
    );
    expect(container.querySelector(".overflow-x-auto"), "nothing scrolls sideways").toBeNull();
    const run = container.querySelector(".flex-wrap");
    expect(run, "the season run wraps").toBeTruthy();
    expect(container.querySelectorAll("a[href*='/draft/']").length).toBe(7);
    // It mirrors SegmentControl's paint by hand (these are Links, so they keep
    // middle-click) — assert the copy has not drifted from the original.
    const current = container.querySelector("a[aria-current='true']");
    expect(current?.className, "the current season takes the stamp underline")
      .toMatch(/after:bg-stamp/);
  });

  it("states ADP coverage rather than implying full coverage", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          owners: [{ ...base.owners[0], graded_picks: 11, total_picks: 15 }],
        }}
      />,
    );
    // Two homes now: the desktop Owners table's Coverage column and the
    // mobile owner card's Coverage fact. Both are the same claim, and the
    // file's own convention is getAllByText for a two-variant render.
    expect(screen.getAllByText(/11 of 15/).length).toBeGreaterThan(0);
  });

  /* ---- fix 2: dead Coverage figure on the mobile owner card -------------- */

  it("drops Coverage from the mobile owner card when the owner has no ADP figure", () => {
    // `owner_adp_grades` keys off the Sleeper-ADP-specific `adp_delta` field,
    // which is always null on a dynasty rookie class — graded on rookie ECR
    // instead. Line 327's ADP +/- meta was already gated on
    // `adp_total_delta != null`; Coverage sat right above it with no gate at
    // all, printing "Coverage 0 of 3" on every dynasty league's owner card —
    // the exact dead figure a previous fix already removed from the desktop
    // Owners table. No test covered the mobile card, which is why it shipped.
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false, format: "dynasty",
          owners: [{ ...base.owners[0], adp_total_delta: null, graded_picks: 0, total_picks: 3 }],
        }}
      />,
    );
    const mobile = screen.getByTestId("draft-picks-mobile");
    const toggle = within(mobile).getByRole("button", { name: /Alice/ });
    const card = toggle.parentElement as HTMLElement;
    expect(within(card).queryByText("Coverage")).toBeNull();
    expect(within(card).queryByText(/0 of 3/)).toBeNull();
  });

  it("keeps Coverage on the mobile owner card when the owner has an ADP figure", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          // graded_picks/total_picks deliberately distinct from the "1 of 1"
          // Rank denominator (one owner in this fixture) so the two facts
          // can't be confused for one another.
          owners: [{ ...base.owners[0], adp_total_delta: -11, graded_picks: 1, total_picks: 2 }],
        }}
      />,
    );
    const mobile = screen.getByTestId("draft-picks-mobile");
    const toggle = within(mobile).getByRole("button", { name: /Alice/ });
    const card = toggle.parentElement as HTMLElement;
    expect(within(card).getByText("Coverage")).toBeTruthy();
    expect(within(card).getByText(/1 of 2/)).toBeTruthy();
  });

  it("marks keeper picks", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          picks: [{ ...base.picks[0], is_keeper: true }],
        }}
      />,
    );
    // Same desktop + ≤700px-reflow duplication as the player name above.
    expect(screen.getAllByText(/keeper/i).length).toBeGreaterThan(0);
  });

  /* -------------------------------------------------------------------------
   * Fix round 1: hiding the ADP/projection/Total Points columns below 701px
   * with no alternate rendering (`display:none`, nothing else) shipped as
   * the first fix for the fixed-px overflow bug. jsdom doesn't evaluate CSS
   * media queries, so a plain getByText/queryByText assertion can't tell
   * "present but hidden" from "present and reachable" — both put the text
   * in the DOM. These assert against the ≤700px reflow container
   * specifically (`data-testid="draft-picks-mobile"`, the sibling of the
   * ≥701px desktop ledger `hidden`s away below that breakpoint), so a
   * regression back to "desktop-only, hidden on mobile" fails here even
   * though the un-scoped queries above would still pass.
   * ------------------------------------------------------------------------ */
  it("keeps the baseline and projection reachable in the mobile reflow, not just hidden on the desktop row", () => {
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);
    const mobile = screen.getByTestId("draft-picks-mobile");
    // `-11.0` is the owner card's summed ADP +/- AND the single pick's own
    // baseline delta — identical here because the owner made one pick. Both
    // are real readings, so this asserts presence, not uniqueness.
    expect(within(mobile).getAllByText("12.0").length).toBeGreaterThan(0); // baseline
    expect(within(mobile).getAllByText("-11.0").length).toBeGreaterThan(0); // baseline_delta
    expect(within(mobile).getAllByText("210.5").length).toBeGreaterThan(0); // projected
  });

  it("keeps Total Points reachable in the mobile reflow once the class has played", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true,
          picks: [{ ...base.picks[0], production_total: 87.4 }],
        }}
      />,
    );
    const mobile = screen.getByTestId("draft-picks-mobile");
    expect(within(mobile).getAllByText("87.4").length).toBeGreaterThan(0);
  });

  /* ---- grouped-by-owner mobile board ---------------------------------- */

  it("labels a pick by round and slot, not by overall number", () => {
    // `pick_no` alone tells you nothing about the shape of the draft: in a
    // 12-team league pick 13 opens round 2, and a reader should not divide by
    // the team count to learn that. `round`/`slot` are both on the payload.
    // Rendered two-tone (round dim, slot in ink) as sibling spans, so a plain
    // getByText can't see the whole "1.01" — `pickNoTexts` reads each
    // `data-testid="pick-no"` node's full `textContent` instead.
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);
    const mobile = screen.getByTestId("draft-picks-mobile");
    expect(pickNoTexts(mobile)).toContain("1.01");
  });

  it("shows Pick as round·slot on the desktop row too, not the flattened overall number", () => {
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);
    const desktop = screen.getByTestId("draft-picks-desktop");
    expect(within(desktop).getByText("Pick")).toBeTruthy();
    expect(pickNoTexts(desktop)).toContain("1.01");
    expect(within(desktop).queryByText("#")).toBeNull();
  });

  /* ---- snake-draft round 2: position-within-round, not draft slot ------- */

  it("labels round 2 of a snake draft by position within the round, not draft slot, and ascends", () => {
    // Real 2025-class data: a 12-team snake draft where round 2 runs in
    // reverse slot order. `slot` alone rendered "2.12", "2.11", "2.10" —
    // wrong AND counting down. The correct label is round 2's own pick
    // order: "2.01", "2.02", "2.03", ascending.
    const snakeRound2 = {
      ...base, graded: false,
      picks: [
        { ...base.picks[0], player_id: "p1", pick_no: 12, round: 1, slot: 12, picks_in_round: 12, full_name: "Round 1 Pick" },
        { ...base.picks[0], player_id: "p2", pick_no: 13, round: 2, slot: 12, picks_in_round: 12, full_name: "Round 2 First" },
        { ...base.picks[0], player_id: "p3", pick_no: 14, round: 2, slot: 11, picks_in_round: 12, full_name: "Round 2 Second" },
        { ...base.picks[0], player_id: "p4", pick_no: 15, round: 2, slot: 10, picks_in_round: 12, full_name: "Round 2 Third" },
      ],
    };
    render(<DraftBoard leagueId="lg" board={snakeRound2} />);

    const desktop = screen.getByTestId("draft-picks-desktop");
    const desktopLabels = pickNoTexts(desktop);
    expect(desktopLabels).toContain("1.12");
    expect(desktopLabels).toContain("2.01");
    expect(desktopLabels).toContain("2.02");
    expect(desktopLabels).toContain("2.03");
    expect(desktopLabels).not.toContain("2.12");
    expect(desktopLabels).not.toContain("2.11");
    expect(desktopLabels).not.toContain("2.10");
    // Rows sort by pick_no, so the round-2 labels must read in ascending
    // order — the symptom a reader notices first.
    const round2Labels = desktopLabels.filter((t) => t.startsWith("2."));
    expect(round2Labels).toEqual(["2.01", "2.02", "2.03"]);

    const mobile = screen.getByTestId("draft-picks-mobile");
    const mobileLabels = pickNoTexts(mobile);
    expect(mobileLabels).toContain("2.01");
    expect(mobileLabels).toContain("2.02");
    expect(mobileLabels).toContain("2.03");
    expect(mobileLabels).not.toContain("2.12");
  });

  it("falls back to slot for the pick position on a bad/partial derivation", () => {
    // Guard: with no picks_in_round on the row at all (a pre-feature cached
    // response), a round/pick_no combination that doesn't divide out to a
    // positive position must not render zero or a negative number.
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          picks: [{ ...base.picks[0], pick_no: 1, round: 2, slot: 5, picks_in_round: undefined }],
        }}
      />,
    );
    const desktop = screen.getByTestId("draft-picks-desktop");
    expect(pickNoTexts(desktop)).toContain("2.05");
  });

  it("labels round 2 ascending across a full board, matching a real 12-team snake class", () => {
    // A full 12-team, 2-round class (matching the real fixture's shape), with
    // `picks_in_round` on every row the way a real response always sends it
    // (`draft_results.py` emits it on every drafted-pick row).
    const teamCount = 12;
    const round1 = Array.from({ length: teamCount }, (_, i) => ({
      ...base.picks[0], player_id: `r1p${i + 1}`, pick_no: i + 1, round: 1, slot: i + 1,
      picks_in_round: teamCount, full_name: `R1 Pick ${i + 1}`,
    }));
    const round2 = Array.from({ length: teamCount }, (_, i) => ({
      ...base.picks[0], player_id: `r2p${i + 1}`, pick_no: teamCount + i + 1, round: 2,
      slot: teamCount - i, picks_in_round: teamCount, full_name: `R2 Pick ${i + 1}`,
    }));
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false, picks: [...round1, ...round2] }} />);
    const desktop = screen.getByTestId("draft-picks-desktop");
    const round2Labels = pickNoTexts(desktop).filter((t) => t.startsWith("2."));
    expect(round2Labels.slice(0, 3)).toEqual(["2.01", "2.02", "2.03"]);
    expect(round2Labels).toEqual([...round2Labels].sort());
  });

  it("groups picks under their owner, and keeps pick order one tap away", async () => {
    const user = userEvent.setup();
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);
    const mobile = screen.getByTestId("draft-picks-mobile");

    // Default view is by owner: the owner is a disclosure, not a stat cell.
    const group = within(mobile).getByRole("button", { name: /Alice/ });
    expect(group.getAttribute("aria-expanded")).toBe("false");

    // Pick order is a first-class route, not a trade-off.
    await user.click(within(mobile).getByRole("button", { name: /^By pick$/i }));
    expect(within(mobile).queryByRole("button", { name: /Alice/ })).toBeNull();
    expect(within(mobile).getAllByText("Player One").length).toBeGreaterThan(0);
  });

  it("keeps every pick field inside the group — deferred, never dropped", async () => {
    const user = userEvent.setup();
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: true }} />);
    const mobile = screen.getByTestId("draft-picks-mobile");
    const group = within(mobile).getByRole("button", { name: /Alice/ });
    const body = document.getElementById(group.getAttribute("aria-controls")!)!;

    // In the DOM while collapsed — find-in-page still reaches it, and the
    // "no column may be lost on a phone" rule is about availability.
    expect(body.hasAttribute("hidden")).toBe(true);
    expect(body.textContent).toMatch(/ADP/);

    await user.click(group);
    expect(body.hasAttribute("hidden")).toBe(false);
    // Proj is deliberately EXCLUDED here, not merely deferred: once graded, a
    // preseason estimate is trivia beside a real result — the same editorial
    // rule the desktop pick row applies (phase 2.5 trim, fix round 1). Every
    // other field the desktop row still carries on a graded pick stays
    // reachable.
    for (const label of ["ADP", "Total"]) {
      expect(within(body).getAllByText(new RegExp(label)).length).toBeGreaterThan(0);
    }
    expect(within(body).queryByText(/Proj/)).toBeNull();
  });

  it("prints no headline at all when a class is unplayed AND has no baseline", () => {
    /* Not hypothetical: ADP is forward-only (`adp_snapshot_store.py` — a draft
     * predating the first daily snapshot has no baseline, permanently), so a
     * real class can carry no baseline at all: `baseline_label: ""`, every
     * pick's `baseline`/`baseline_delta` null, no ADP coverage on any owner.
     * The first build headlined every card with "— ADP +/-": a column of
     * nothing wearing a label, squeezing the player name, which is the only
     * thing such a card actually knows. */
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false, baseline_label: "",
          picks: [{ ...base.picks[0], baseline: null, baseline_delta: null, projected_points: null }],
          owners: [{ ...base.owners[0], adp_total_delta: null, graded_picks: 0, total_picks: 1 }],
        }}
      />,
    );
    const mobile = screen.getByTestId("draft-picks-mobile");
    expect(within(mobile).queryByText("ADP +/-")).toBeNull();
    // The pick is still fully present — the name is the content.
    expect(pickNoTexts(mobile)).toContain("1.01");
    // No owner here has an ADP figure to grade Coverage against — the "0 of 1"
    // this used to print was the dead-figure bug fix 2 removes (see the
    // dedicated Coverage tests below); this scenario now hides it, matching
    // the desktop Owners table's own `hasAdpColumns` gate.
    expect(screen.queryByText(/0 of 1/)).toBeNull();
  });

  /* ---- dynasty rookie ECR baseline -------------------------------------- */

  it("renders ECR as the baseline column header on a dynasty rookie board, and labels the pick delta Slot +/-", () => {
    // Nothing in this file exercised `baseline_label: "ECR"` before — the gap
    // that let I2's three-name drift (Slot +/- / `${baselineLabel} +/-` /
    // ADP +/-) ship without a failing test.
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false, format: "dynasty",
          baseline_label: "ECR",
          picks: [{ ...base.picks[0], baseline_source: "rookie_ecr" }],
        }}
      />,
    );
    expect(screen.getAllByText("ECR").length).toBeGreaterThan(0);
    // The pick-level delta is never the interpolated baseline label
    // ("ECR +/-"). Desktop shortens its own column to "Slot" (Treatment C);
    // the phone card headline still spells out "Slot +/-".
    expect(screen.getAllByText("Slot").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Slot +/-").length).toBeGreaterThan(0);
    expect(screen.queryByText("ECR +/-")).toBeNull();
  });

  /* ---- I1: Owners panel drops dead ADP columns on a dynasty board ------- */

  it("drops ADP +/- and Coverage from the Owners panel when no owner carries an ADP figure", () => {
    // Dynasty: `adp_total_delta` is always null (no Sleeper market baseline
    // for rookies). Rendering the two columns anyway prints "Coverage 0 of N"
    // directly above the Picks ledger's real ECR-graded rows — a headline
    // that contradicts the rows beneath it.
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true, format: "dynasty",
          owners: [{ ...base.owners[0], adp_total_delta: null }],
        }}
      />,
    );
    const owners = screen.getByRole("table", { name: /draft board owners/i });
    // Treatment C shortened the desktop labels ("ADP +/-" → "ADP",
    // "Coverage" → "Cov"); the tooltip still carries the full name.
    expect(within(owners).queryByText("ADP")).toBeNull();
    expect(within(owners).queryByText("Cov")).toBeNull();
    // Total Points still renders — this class is graded.
    expect(within(owners).getByText(/total points/i)).toBeTruthy();
  });

  it("keeps ADP and Cov in the Owners panel when at least one owner has an ADP figure", () => {
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);
    const owners = screen.getByRole("table", { name: /draft board owners/i });
    expect(within(owners).getByText("ADP")).toBeTruthy();
    expect(within(owners).getByText("Cov")).toBeTruthy();
  });

  /* ---- Start % ------------------------------------------------------- */

  it("renders an em-dash rather than 0% for a pick that never scored", () => {
    render(<DraftBoard leagueId="lg" board={{
      ...base, graded: true,
      picks: [{ ...base.picks[0], production_total: 0, production_started: 0 }],
    }} />);
    expect(screen.queryByText("0%")).toBeNull();
  });

  it("shows Start % as a whole percentage of Total Points", () => {
    render(<DraftBoard leagueId="lg" board={{
      ...base, graded: true,
      picks: [{ ...base.picks[0], production_total: 200, production_started: 60 }],
    }} />);
    expect(screen.getAllByText("30%").length).toBeGreaterThan(0);
  });

  /* ---- Points Above Round (mobile owner headline) --------------------- */

  it("shows Points Above Round, not Total Points, as the mobile owner headline once graded", () => {
    // Mirrors the desktop Owners table's own prominence swap
    // (`DraftPicksMobile.tsx::ownerHeadlineFor`): a graded owner card leads
    // with PAR, the figure the backend actually sorts owners by, not raw
    // Total Points. No test pinned this, so a regression back to Total
    // Points would pass silently.
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true,
          owners: [{ ...base.owners[0], production_total: 123.4, points_above_round: 45.2 }],
        }}
      />,
    );
    const mobile = screen.getByTestId("draft-picks-mobile");
    const group = within(mobile).getByRole("button", { name: /Alice/ });
    expect(within(group).getByText("+45.2")).toBeTruthy();
    expect(within(group).getByText("Points Above Round")).toBeTruthy();
    expect(within(group).queryByText("Total Points")).toBeNull();
  });

  /* ---- E: no invented sign on an arithmetic zero ---------------------- */

  it("renders an arithmetically-zero PAR as dim 0.0, never a signed -0.0", () => {
    // PAR is total - mean, so a value inside (-0.05, 0) is zero once rounded
    // to the one decimal this figure renders at, but still negative as a
    // float. `EntryCard.tsx`'s house rule: "zero or an absent value is
    // --dim, never invent a sign for zero."
    const { container } = render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true,
          owners: [{ ...base.owners[0], points_above_round: -0.01 }],
        }}
      />,
    );
    expect(screen.queryByText("-0.0")).toBeNull();
    // The PAR cell is the only one styled `font-semibold` (`Signed`'s own
    // wrapper), which disambiguates it from the Regular/Playoff/Toilet cells
    // that also happen to read "0.0" in this fixture.
    const cell = container.querySelector(".font-semibold");
    expect(cell?.textContent).toBe("0.0");
    expect(cell?.querySelector("span")?.className).toMatch(/text-dim/);
    expect(cell?.querySelector("span")?.className).not.toMatch(/text-neg-strong/);
    // Same clamp, same house rule, on the mobile owner card's own PAR
    // headline (`DraftPicksMobile.tsx`'s standalone `signed`/`toneOf` copy) —
    // now the only owner PAR view below 701px, so it must not disagree.
    const mobile = screen.getByTestId("draft-picks-mobile");
    expect(within(mobile).queryByText("-0.0")).toBeNull();
  });

  /* ---- A: owner figures reachable below 910px -------------------------- */

  it("hides the desktop Owners table below 910px and surfaces every owner figure in the mobile owner card", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true,
          owners: [{
            ...base.owners[0], graded_picks: 2, total_picks: 2,
            production_total: 120.0, production_started: 60,
            production_regular: 10, production_playoff: 20, production_toilet: 5,
            points_above_round: 45.2,
          }],
        }}
      />,
    );
    const desktop = screen.getByTestId("draft-owners-desktop");
    expect(desktop.className).toMatch(/hidden/);
    expect(desktop.className).toMatch(/min-\[910px\]:block/);

    const mobile = screen.getByTestId("draft-picks-mobile");
    const toggle = within(mobile).getByRole("button", { name: /Alice/ });
    // The button is only the disclosure header — Rank/Picks/Coverage/the
    // graded run sit in the `MetaLine` beneath it, a sibling of the button
    // inside the same `EntryCard`, so the assertions scope to that card.
    const card = toggle.parentElement as HTMLElement;
    // Rank (1 of 1 owner), Picks/Coverage (2 of 2 — deliberately distinct
    // from the rank denominator so the two facts can't be confused for one
    // another), and the full graded run all reach the card.
    expect(within(card).getByText("1 of 1")).toBeTruthy(); // Rank
    expect(within(card).getByText("2 of 2")).toBeTruthy(); // Coverage
    expect(within(card).getByText("120.0")).toBeTruthy(); // Total
    expect(within(card).getByText("50%")).toBeTruthy(); // Start %
    expect(within(card).getByText("10.0")).toBeTruthy(); // Regular
    expect(within(card).getByText("20.0")).toBeTruthy(); // Playoff
    expect(within(card).getByText("5.0")).toBeTruthy(); // Toilet
    expect(within(card).getByText("+45.2")).toBeTruthy(); // PAR headline
  });

  it("still surfaces the summed ADP +/- on the mobile owner card once graded", () => {
    // Once graded the card's headline swaps to PAR — this asserts the ADP
    // delta (the desktop table's ninth `OWNER_GRID_GRADED_ADP` column) isn't
    // silently dropped from the mobile card in that state.
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true,
          owners: [{ ...base.owners[0], adp_total_delta: -11 }],
        }}
      />,
    );
    const mobile = screen.getByTestId("draft-picks-mobile");
    const toggle = within(mobile).getByRole("button", { name: /Alice/ });
    const card = toggle.parentElement as HTMLElement;
    expect(within(card).getByText("ADP +/-")).toBeTruthy();
    expect(within(card).getByText("-11.0")).toBeTruthy();
  });

  /* ---- regression: the two desktop-vs-mobile gates must not drift apart -- */

  it("gates the owners-desktop table at the same breakpoint the picks-mobile reflow hides at", () => {
    // jsdom doesn't evaluate media queries, so a visibility assertion can't
    // tell "switches at 910px" from "switches at 701px" — both just leave the
    // element in the DOM. What's actually being pinned here is the CLASS
    // CONTRACT: `OwnersSection`'s desktop table (`draft-owners-desktop`) and
    // `PicksSection`'s mobile reflow (`draft-picks-mobile`) must carry the
    // same `min-[910px]` breakpoint literal. This is exactly the regression
    // that shipped the bug this test file's own fix commit addresses — Owners
    // was gated at 701px, Picks (and its mobile alternative) at 870px, chosen
    // independently of each other, opening a 701–869px band where the owner
    // rollup rendered twice: once in the desktop Owners table, once in
    // `DraftPicksMobile`'s `OwnerGroup` cards. If either breakpoint is ever
    // "helpfully" changed without touching the other, this fails. (The shared
    // gate itself later moved 870 → 910 — see `draft-columns.test.ts`'s width
    // budget suite — but it moved on BOTH sides at once, so this test's own
    // contract, "same literal on both", never broke.)
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);

    const ownersDesktop = screen.getByTestId("draft-owners-desktop");
    const picksDesktop = screen.getByTestId("draft-picks-desktop");
    const picksMobile = screen.getByTestId("draft-picks-mobile");

    // Owners desktop table and Picks desktop table appear at the same width.
    expect(ownersDesktop.className).toMatch(/hidden/);
    expect(ownersDesktop.className).toMatch(/min-\[910px\]:block/);
    expect(picksDesktop.className).toMatch(/hidden/);
    expect(picksDesktop.className).toMatch(/min-\[910px\]:block/);

    // Picks mobile reflow (which also carries the owner rollup via
    // `DraftPicksMobile`'s `OwnerGroup`) disappears at that same width, never
    // lower — so the owners-desktop table is never gated at a narrower
    // breakpoint than the width at which the mobile owner cards hide.
    expect(picksMobile.className).toMatch(/min-\[910px\]:hidden/);
  });

  /* ---- phase 2.5: trim the board's pick rows to what the board is for --- */

  it("keeps the board's pick rows to what the board is for", () => {
    // The board answers "who drafted well". Regular/Playoff/Toilet are a
    // question about one manager, so they live on the OWNER rows and the owner
    // Draft tab, not on 36 pick rows nobody scans. See the spec's column budget.
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: true }} />);
    const desktop = screen.getByTestId("draft-picks-desktop");
    expect(within(desktop).queryByText("Regular")).toBeNull();
    expect(within(desktop).queryByText("Playoff")).toBeNull();
    expect(within(desktop).queryByText("Toilet")).toBeNull();
    // What stays: "Total" — the Picks header's own abbreviation of Total
    // Points (fix 4), which fits its column on one line where the full label
    // wrapped. The Owners table two sections up keeps the unabbreviated name.
    // "Start %" is likewise shortened to "Start" on desktop (Treatment C).
    expect(within(desktop).getAllByText("Total").length).toBeGreaterThan(0);
    expect(within(desktop).getAllByText("Start").length).toBeGreaterThan(0);
  });

  it("drops Projected once a class is graded, and keeps it while unplayed", () => {
    // A preseason estimate is superseded by what actually happened. On an
    // unplayed class it is the only forward-looking figure there is.
    const withProj = { ...base, picks: [{ ...base.picks[0], projected_points: 210.5 }] };
    const { rerender } = render(
      <DraftBoard leagueId="lg" board={{ ...withProj, graded: false }} />);
    expect(within(screen.getByTestId("draft-picks-desktop")).getAllByText("Proj").length)
      .toBeGreaterThan(0);
    rerender(<DraftBoard leagueId="lg" board={{ ...withProj, graded: true }} />);
    expect(within(screen.getByTestId("draft-picks-desktop")).queryByText("Proj")).toBeNull();
  });

  it("still shows every metric on the owner rows and the phone cards", () => {
    // The trim is about the BOARD'S PICK ROWS only. Losing these anywhere else
    // would be data loss, not editing.
    render(<DraftBoard leagueId="lg" board={{ ...base, graded: true }} />);
    const owners = screen.getByTestId("draft-owners-desktop");
    expect(within(owners).getAllByText("Regular").length).toBeGreaterThan(0);
    expect(within(owners).getAllByText("Playoff").length).toBeGreaterThan(0);
    expect(within(owners).getAllByText("Toilet").length).toBeGreaterThan(0);
  });

  it("drops Projected on a graded class on the phone too, matching the desktop row", () => {
    // Editorial, not spatial: a preseason estimate is trivia beside a real
    // result, and the two surfaces must not disagree about what a graded pick
    // shows. Rotating past the breakpoint should not make a column appear.
    const withProj = { ...base, picks: [{ ...base.picks[0], projected_points: 210.5 }] };
    const { rerender } = render(
      <DraftBoard leagueId="lg" board={{ ...withProj, graded: false }} />);
    expect(within(screen.getByTestId("draft-picks-mobile")).getAllByText("210.5").length)
      .toBeGreaterThan(0);
    rerender(<DraftBoard leagueId="lg" board={{ ...withProj, graded: true }} />);
    expect(within(screen.getByTestId("draft-picks-mobile")).queryByText("210.5")).toBeNull();
  });

  /* ---- Task 6: Hit/Average/Bust verdict column -------------------------- */

  it("shows the Verdict column, coloured by outcome, once the class carries verdicts", () => {
    // A verdict needs production to judge AND a rookie-ECR baseline to judge
    // it against, so it only ever appears graded, on a dynasty rookie board.
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true, format: "dynasty", baseline_label: "ECR", has_verdicts: true,
          picks: [
            { ...base.picks[0], baseline_source: "rookie_ecr", verdict: "hit" },
            {
              ...base.picks[0], player_id: "p2", pick_no: 2, full_name: "Player Two",
              baseline_source: "rookie_ecr", verdict: "bust",
            },
          ],
        }}
      />,
    );
    const desktop = screen.getByTestId("draft-picks-desktop");
    expect(within(desktop).getAllByText("Verdict").length).toBeGreaterThan(0);
    const hit = within(desktop).getAllByText("Hit")[0];
    expect(hit.className).toMatch(/text-pos-strong/);
    const bust = within(desktop).getAllByText("Bust")[0];
    expect(bust.className).toMatch(/text-neg-strong/);

    const mobile = screen.getByTestId("draft-picks-mobile");
    expect(within(mobile).getAllByText("Hit").length).toBeGreaterThan(0);
    expect(within(mobile).getAllByText("Bust").length).toBeGreaterThan(0);
  });

  it("drops the Verdict column entirely when nothing in the class can be judged", () => {
    // A header over a column of dashes is worse than no column — `has_verdicts`
    // gates the whole column, not just the value cells.
    render(
      <DraftBoard
        leagueId="lg"
        board={{ ...base, graded: true, format: "dynasty", has_verdicts: false }}
      />,
    );
    const desktop = screen.getByTestId("draft-picks-desktop");
    expect(within(desktop).queryByText("Verdict")).toBeNull();
    const mobile = screen.getByTestId("draft-picks-mobile");
    expect(within(mobile).queryByText("Verdict")).toBeNull();
  });

  it("never renders KTC on the Verdict column", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: true, format: "dynasty", has_verdicts: true,
          picks: [{ ...base.picks[0], baseline_source: "rookie_ecr", verdict: "average" }],
        }}
      />,
    );
    expect(screen.queryByText(/KTC/)).toBeNull();
  });

  /* ---- fix 5: the `now` (roster status) column ---------------------------
   * Spec's own column table reads "pick · owner · player · baseline ·
   * slot +/- · verdict · Total Points · Start % · GS · now" — `now` was
   * specced and never built. `roster_status` is unconditional (every pick
   * has a current standing), unlike Verdict/baseline which gate on the
   * class's own data. */

  it("shows the Now column, coloured mono text following PastPicksTable's Status treatment", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          picks: [
            { ...base.picks[0], roster_status: "rostered" },
            { ...base.picks[0], player_id: "p2", pick_no: 2, round: 1, slot: 2, full_name: "Player Two", roster_status: "dropped" },
            { ...base.picks[0], player_id: "p3", pick_no: 3, round: 1, slot: 3, full_name: "Player Three", roster_status: "traded" },
          ],
        }}
      />,
    );
    const desktop = screen.getByTestId("draft-picks-desktop");
    expect(within(desktop).getAllByText("Now").length).toBeGreaterThan(0);
    const rostered = within(desktop).getAllByText("Rostered")[0];
    expect(rostered.className).toMatch(/text-pos-strong/);
    const dropped = within(desktop).getAllByText("Dropped")[0];
    expect(dropped.className).toMatch(/text-neg-strong/);
    // Trading a player away is a decision, not a failure — neutral, same tone
    // Verdict's "average" and an unknown status both use.
    const traded = within(desktop).getAllByText("Traded")[0];
    expect(traded.className).toMatch(/text-dim/);
    expect(traded.className).not.toMatch(/text-pos-strong|text-neg-strong/);
  });

  it("carries the Now status into the mobile reflow too", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          picks: [{ ...base.picks[0], roster_status: "dropped" }],
        }}
      />,
    );
    const mobile = screen.getByTestId("draft-picks-mobile");
    expect(within(mobile).getAllByText("Now").length).toBeGreaterThan(0);
    const dropped = within(mobile).getAllByText("Dropped")[0];
    expect(dropped.className).toMatch(/text-neg-strong/);
  });

  it("renders an em-dash for Now rather than guessing, on a pre-feature response with no roster_status", () => {
    render(
      <DraftBoard
        leagueId="lg"
        board={{
          ...base, graded: false,
          picks: [{ ...base.picks[0], roster_status: undefined }],
        }}
      />,
    );
    const desktop = screen.getByTestId("draft-picks-desktop");
    expect(within(desktop).queryByText("Rostered")).toBeNull();
    expect(within(desktop).queryByText("Dropped")).toBeNull();
    const mobile = screen.getByTestId("draft-picks-mobile");
    expect(within(mobile).queryByText("Rostered")).toBeNull();
  });

  /* ---- Task 2: per-column sorting ---------------------------------------
   * `SortButton.prompt.md`: "Sorting a ledger must reorder BOTH bodies — the
   * desktop rows and the mobile EntryCards. Reordering only the rows
   * desynchronises them, which is invisible on desktop and wrong on a
   * phone." `PicksSection` derives ONE sorted array (`web/lib/draft-sort.ts`)
   * and feeds both the desktop table and `DraftPicksMobile` from it — these
   * tests are what catches a regression back to sorting only one body. */
  describe("sorting", () => {
    const multi = {
      ...base,
      graded: true,
      picks: [
        { ...base.picks[0], player_id: "p1", pick_no: 1, round: 1, slot: 1, picks_in_round: 3, full_name: "Player One", production_total: 50 },
        { ...base.picks[0], player_id: "p2", pick_no: 2, round: 1, slot: 2, picks_in_round: 3, full_name: "Player Two", production_total: 150 },
        { ...base.picks[0], player_id: "p3", pick_no: 3, round: 1, slot: 3, picks_in_round: 3, full_name: "Player Three", production_total: 100 },
      ],
    };

    it("reorders the desktop rows when a picks column header is clicked", async () => {
      const user = userEvent.setup();
      render(<DraftBoard leagueId="lg" board={multi} />);
      const desktop = screen.getByTestId("draft-picks-desktop");

      // Natural draft order before any sort.
      expect(within(desktop).getAllByText(/^Player (One|Two|Three)$/).map((el) => el.textContent))
        .toEqual(["Player One", "Player Two", "Player Three"]);

      // First click on a numeric column ("Total") opens descending — the
      // highest total first. Queried by the SortButton's accessible name
      // ("Sort by Total…"), not the bare visible text — see SortButton.tsx.
      await user.click(within(desktop).getByRole("button", { name: /^Sort by Total\b/ }));
      expect(within(desktop).getAllByText(/^Player (One|Two|Three)$/).map((el) => el.textContent))
        .toEqual(["Player Two", "Player Three", "Player One"]);
    });

    it("reorders the phone cards identically to the desktop rows — the desync the spec calls out", async () => {
      const user = userEvent.setup();
      render(<DraftBoard leagueId="lg" board={multi} />);
      const desktop = screen.getByTestId("draft-picks-desktop");
      const mobile = screen.getByTestId("draft-picks-mobile");

      await user.click(within(desktop).getByRole("button", { name: /^Sort by Total\b/ }));
      const desktopOrder = within(desktop).getAllByText(/^Player (One|Two|Three)$/).map((el) => el.textContent);

      // The mobile reflow defaults to grouped-by-owner; switch to the flat
      // "By pick" view, the direct analogue of the desktop's one-row-per-pick
      // table, and read pick order off IT — not the owner grouping, which
      // answers a different question.
      await user.click(within(mobile).getByRole("button", { name: /^By pick$/i }));
      const mobileOrder = within(mobile).getAllByText(/^Player (One|Two|Three)$/).map((el) => el.textContent);

      expect(mobileOrder).toEqual(desktopOrder);
    });

    it("moves aria-sort to the clicked column's columnheader and returns the previous column to none", async () => {
      // `aria-sort` is only valid on columnheader/rowheader/gridcell — it is
      // dropped by the accessibility layer on role="button", so this asserts
      // on the WRAPPING columnheader cell, not the SortButton inside it
      // (that's what let this table ship with no sort state announced at
      // all — see SortButton.tsx / DraftBoard.tsx's DefinedHeader docstring).
      const user = userEvent.setup();
      render(<DraftBoard leagueId="lg" board={multi} />);
      const desktop = screen.getByTestId("draft-picks-desktop");

      const totalButton = within(desktop).getByRole("button", { name: /^Sort by Total\b/ });
      const totalHeader = totalButton.closest('[role="columnheader"]') as HTMLElement;
      expect(totalHeader).toBeTruthy();
      // The button itself never carries aria-sort, in any state.
      expect(totalButton.hasAttribute("aria-sort")).toBe(false);
      expect(totalHeader.getAttribute("aria-sort")).toBe("none");
      await user.click(totalButton);
      expect(totalHeader.getAttribute("aria-sort")).toBe("descending");
      expect(totalButton.hasAttribute("aria-sort")).toBe(false);

      const gsButton = within(desktop).getByRole("button", { name: /^Sort by GS\b/ });
      const gsHeader = gsButton.closest('[role="columnheader"]') as HTMLElement;
      await user.click(gsButton);
      expect(gsHeader.getAttribute("aria-sort")).toBe("descending");
      // Switching columns resets the previously-active one to "none" — only
      // one column is ever sorted at a time.
      expect(totalHeader.getAttribute("aria-sort")).toBe("none");
    });

    it("carries aria-sort on the identity columnheaders too, not just the DefinedHeader metric columns", async () => {
      // Pick/Owner/Player (Picks) and #/Owner (Owners) are bare `role="columnheader"`
      // divs, not routed through `DefinedHeader` — they need the same
      // aria-sort wiring inline, or a screen reader announces sort state for
      // some sortable columns and silently not others.
      const user = userEvent.setup();
      render(<DraftBoard leagueId="lg" board={multi} />);
      const desktop = screen.getByTestId("draft-picks-desktop");

      const ownerButton = within(desktop).getByRole("button", { name: /^Sort by Owner\b/ });
      const ownerHeader = ownerButton.closest('[role="columnheader"]') as HTMLElement;
      expect(ownerHeader.getAttribute("aria-sort")).toBe("none");
      await user.click(ownerButton);
      expect(ownerHeader.getAttribute("aria-sort")).toBe("ascending");

      const owners = screen.getByTestId("draft-owners-desktop");
      const rankButton = within(owners).getByRole("button", { name: /^Sort by #/ });
      const rankHeader = rankButton.closest('[role="columnheader"]') as HTMLElement;
      expect(rankHeader.getAttribute("aria-sort")).toBe("none");
      await user.click(rankButton);
      expect(rankHeader.getAttribute("aria-sort")).toBe("descending");
    });

    it("never puts aria-sort on the non-sortable Proj column — omitted, not \"none\"", () => {
      // `"none"` claims the column is sortable but currently unsorted; Proj
      // has no sort key at all, so the attribute must be absent outright.
      const withProj = { ...base, graded: false, picks: [{ ...base.picks[0], projected_points: 210.5 }] };
      render(<DraftBoard leagueId="lg" board={withProj} />);
      const desktop = screen.getByTestId("draft-picks-desktop");
      const projHeader = within(desktop).getByText("Proj").closest('[role="columnheader"]') as HTMLElement;
      expect(projHeader.hasAttribute("aria-sort")).toBe(false);
    });

    it("sorts unlabelled verdict rows last, not first, when sorting Verdict descending", async () => {
      const user = userEvent.setup();
      render(
        <DraftBoard
          leagueId="lg"
          board={{
            ...multi, format: "dynasty", baseline_label: "ECR", has_verdicts: true,
            picks: [
              { ...multi.picks[0], baseline_source: "rookie_ecr", verdict: "bust", full_name: "Bust Guy" },
              { ...multi.picks[1], baseline_source: "rookie_ecr", verdict: undefined, full_name: "No Verdict Guy" },
              { ...multi.picks[2], baseline_source: "rookie_ecr", verdict: "hit", full_name: "Hit Guy" },
            ],
          }}
        />,
      );
      const desktop = screen.getByTestId("draft-picks-desktop");
      await user.click(within(desktop).getByRole("button", { name: /^Sort by Verdict\b/ }));

      // Hit → Bust (ordinal, best-first on descending); the unlabelled pick,
      // which has no reading on this column at all, sorts last regardless of
      // direction — never first, where it would read as the best pick.
      expect(within(desktop).getAllByText(/Guy$/).map((el) => el.textContent))
        .toEqual(["Hit Guy", "Bust Guy", "No Verdict Guy"]);
    });

    /* ---- fix round 1: the Owners ledger's mobile body was never synced ----
     * `DraftPicksMobile.tsx` lines 42-57: "THIS IS ALSO THE OWNERS SECTION
     * NOW... Below 910px the `OwnerGroup` card below is the ONLY place the
     * owner rollup is reachable" — the same 910px breakpoint the desktop
     * Owners table hides at. `OwnersSection`'s sort state used to live
     * locally inside `OwnersSection` itself, so `PicksSection` forwarded the
     * raw, unsorted `board.owners` into `DraftPicksMobile`'s default "By
     * owner" view: sorting the desktop Owners table did nothing to the only
     * owner rollup a phone reader can reach. `DraftBoard` now owns the
     * owners sort state and threads ONE sorted array into both
     * `OwnersSection` and `PicksSection` (→ `DraftPicksMobile`). */
    const multiOwners = {
      ...multi,
      owners: [
        { user_id: "u1", owner: { user_id: "u1", owner_name: "Alice" }, adp_total_delta: null, graded_picks: 1, total_picks: 1, production_total: 50 },
        { user_id: "u2", owner: { user_id: "u2", owner_name: "Bob" }, adp_total_delta: null, graded_picks: 1, total_picks: 1, production_total: 150 },
        { user_id: "u3", owner: { user_id: "u3", owner_name: "Carol" }, adp_total_delta: null, graded_picks: 1, total_picks: 1, production_total: 100 },
      ],
    };

    /** The `OwnerGroup` disclosure buttons, in rendered (DOM) order — scoped
     *  by `aria-expanded` so the two `SegmentControl` toggle buttons ("By
     *  owner" / "By pick") sitting in the same container never match. */
    function ownerGroupOrder(container: HTMLElement): (string | undefined)[] {
      return within(container)
        .getAllByRole("button", { expanded: false })
        .map((b) => b.textContent?.match(/Alice|Bob|Carol/)?.[0]);
    }

    it("reorders the desktop Owners rows when a column header is clicked", async () => {
      const user = userEvent.setup();
      render(<DraftBoard leagueId="lg" board={multiOwners} />);
      const desktop = screen.getByTestId("draft-owners-desktop");

      // Natural (backend-sent) order before any sort.
      expect(within(desktop).getAllByText(/^(Alice|Bob|Carol)$/).map((el) => el.textContent))
        .toEqual(["Alice", "Bob", "Carol"]);

      // First click on a numeric column ("Total Points") opens descending.
      await user.click(within(desktop).getByRole("button", { name: /^Sort by Total Points\b/ }));
      expect(within(desktop).getAllByText(/^(Alice|Bob|Carol)$/).map((el) => el.textContent))
        .toEqual(["Bob", "Carol", "Alice"]);
    });

    it("reorders the mobile 'By owner' cards identically to the desktop Owners rows", async () => {
      const user = userEvent.setup();
      render(<DraftBoard leagueId="lg" board={multiOwners} />);
      const desktop = screen.getByTestId("draft-owners-desktop");
      const mobile = screen.getByTestId("draft-picks-mobile");

      // Sanity: "By owner" is the mobile reflow's default view, and it's the
      // ONLY reachable form of the owner rollup below 910px.
      expect(ownerGroupOrder(mobile)).toEqual(["Alice", "Bob", "Carol"]);

      await user.click(within(desktop).getByRole("button", { name: /^Sort by Total Points\b/ }));
      const desktopOrder = within(desktop).getAllByText(/^(Alice|Bob|Carol)$/).map((el) => el.textContent);

      expect(ownerGroupOrder(mobile)).toEqual(desktopOrder);
    });

    /* ---- fix round 2: the mobile Rank badge silently renumbered ----------
     * `DraftPicksMobile.tsx`'s own docstring used to justify `rank={i + 1}`
     * with "this list is already sorted PAR-first... so the rank is a read
     * of that order" — true before fix round 1, false after it, once
     * `owners` started arriving as the user's live sort order rather than
     * the fixed backend order. The desktop table's own "#" column already
     * guards against exactly this (`rankOf`, built from the PRE-sort order);
     * this test pins the same guard on the mobile card's "Rank" `Meta`. */
    it("keeps each mobile owner card's Rank badge fixed to its natural PAR/ADP order, not its position after a desktop sort", async () => {
      const user = userEvent.setup();
      render(<DraftBoard leagueId="lg" board={multiOwners} />);
      const desktop = screen.getByTestId("draft-owners-desktop");
      const mobile = screen.getByTestId("draft-picks-mobile");

      // Sort desktop by Total Points — Bob (natural rank 2 of 3, sent
      // second) becomes visually first.
      await user.click(within(desktop).getByRole("button", { name: /^Sort by Total Points\b/ }));
      expect(within(desktop).getAllByText(/^(Alice|Bob|Carol)$/).map((el) => el.textContent))
        .toEqual(["Bob", "Carol", "Alice"]);

      // Bob's mobile card must still read his FIXED natural rank — "2 of 3"
      // — never his new on-screen position ("1 of 3"), which is what a
      // naive `rank={i + 1}` off the now-sorted `owners` array would print.
      const bobToggle = within(mobile).getByRole("button", { name: /Bob/ });
      const bobCard = bobToggle.parentElement as HTMLElement;
      expect(within(bobCard).getByText("2 of 3")).toBeTruthy();
      expect(within(bobCard).queryByText("1 of 3")).toBeNull();

      // Carol (natural rank 3) moves to the middle position but must still
      // read her own fixed rank too — not "2 of 3", which would collide
      // with Bob's real rank above.
      const carolToggle = within(mobile).getByRole("button", { name: /Carol/ });
      const carolCard = carolToggle.parentElement as HTMLElement;
      expect(within(carolCard).getByText("3 of 3")).toBeTruthy();
    });
  });

  /* ---- Task 3: grouped header and definition tooltips ------------------- */
  describe("grouped header and definition tooltips", () => {
    const gradedVerdictBoard = {
      ...base, graded: true, format: "dynasty", baseline_label: "ECR", has_verdicts: true,
      picks: [{ ...base.picks[0], baseline_source: "rookie_ecr", verdict: "hit" }],
    };

    it("renders the naming tier on a graded, verdicted class, with the Production cap spanning exactly the production columns", () => {
      // GRID_PB_VERDICT (10 tracks): identity(3, capless) | Baseline(2) |
      // Verdict(1, capless — a single column groups nothing) | Production(3)
      // | Now(1, capless). Five caps total; only Baseline and Production
      // carry a label.
      render(<DraftBoard leagueId="lg" board={gradedVerdictBoard} />);
      const desktop = screen.getByTestId("draft-picks-desktop");
      const caps = within(desktop).getAllByRole("columnheader").filter((h) => h.hasAttribute("aria-colspan"));
      expect(caps.length).toBe(5);
      const productionCap = caps.find((c) => c.textContent === "Production");
      expect(productionCap, "a Production cap exists").toBeTruthy();
      // Total · Start % · GS
      expect(productionCap!.getAttribute("aria-colspan")).toBe("3");
      expect(caps.some((c) => c.textContent === "Baseline")).toBe(true);
      // Never re-labelled "Points" — only Total is a points figure.
      expect(caps.some((c) => c.textContent === "Points")).toBe(false);
      // Identity, Verdict, and Now are each capless (`GroupedHead`'s own
      // "Omit for an ungrouped run" rule) — three of the five caps render
      // empty text; only Baseline and Production carry a label.
      expect(caps.filter((c) => c.textContent === "").length).toBe(3);
    });

    it("renders no naming tier on a narrow (no baseline, ungraded) class", () => {
      // GRID_P_PLAIN — 4 tracks, well under the eight-column floor.
      render(<DraftBoard leagueId="lg" board={{ ...base, graded: false }} />);
      const desktop = screen.getByTestId("draft-picks-desktop");
      expect(desktop.querySelectorAll("[aria-colspan]").length).toBe(0);
    });

    it("gives every non-identity Picks column header exactly one tooltip trigger, and identity columns none", () => {
      render(<DraftBoard leagueId="lg" board={gradedVerdictBoard} />);
      const desktop = screen.getByTestId("draft-picks-desktop");
      const headers = labelHeaders(desktop);
      // Pick · Owner · Player is identity; every other header on this fully
      // grouped fixture (ECR, Slot +/-, Verdict, Total, Start %, GS, Now) is
      // non-identity.
      const identityCount = headers.filter((h) => infoTriggers(h).length === 0).length;
      expect(identityCount).toBe(3);
      const nonIdentity = headers.filter((h) => infoTriggers(h).length > 0);
      expect(nonIdentity.length).toBe(headers.length - 3);
      for (const h of nonIdentity) {
        expect(infoTriggers(h).length, `${h.textContent} carries exactly one trigger`).toBe(1);
      }
    });

    it("gives every non-identity Owners column header exactly one tooltip trigger, and identity columns none", () => {
      render(
        <DraftBoard
          leagueId="lg"
          board={{ ...base, graded: true, owners: [{ ...base.owners[0], adp_total_delta: -11 }] }}
        />,
      );
      const owners = screen.getByTestId("draft-owners-desktop");
      const headers = labelHeaders(owners);
      // # · Owner is identity; PAR/Total/Start %/Regular/Playoff/Toilet/ADP+-/Coverage are not.
      const identityCount = headers.filter((h) => infoTriggers(h).length === 0).length;
      expect(identityCount).toBe(2);
      const nonIdentity = headers.filter((h) => infoTriggers(h).length > 0);
      expect(nonIdentity.length).toBe(headers.length - 2);
      for (const h of nonIdentity) {
        expect(infoTriggers(h).length, `${h.textContent} carries exactly one trigger`).toBe(1);
      }
    });

    it("renders the Owners naming tier's Production cap over exactly the five-metric run", () => {
      render(
        <DraftBoard
          leagueId="lg"
          board={{ ...base, graded: true, owners: [{ ...base.owners[0], adp_total_delta: -11 }] }}
        />,
      );
      const owners = screen.getByTestId("draft-owners-desktop");
      const caps = within(owners).getAllByRole("columnheader").filter((h) => h.hasAttribute("aria-colspan"));
      const productionCap = caps.find((c) => c.textContent === "Production");
      expect(productionCap, "a Production cap exists").toBeTruthy();
      // Total · Start % · Regular · Playoff · Toilet
      expect(productionCap!.getAttribute("aria-colspan")).toBe("5");
      // Never re-labelled "Points" — only "Total Points" among this run says
      // "Points" at all; Regular/Playoff/Toilet don't.
      expect(caps.some((c) => c.textContent === "Points")).toBe(false);
    });

    it("never ships a tooltip trigger with an empty definition body — Picks ledger", () => {
      render(<DraftBoard leagueId="lg" board={gradedVerdictBoard} />);
      const desktop = screen.getByTestId("draft-picks-desktop");
      const triggers = within(desktop).getAllByRole("button", { name: /^info:/ });
      expect(triggers.length).toBeGreaterThan(0);
      for (const trigger of triggers) {
        fireEvent.mouseEnter(trigger);
        const tooltip = screen.getByRole("tooltip");
        // Scope to the BODY span specifically (`.text-body`, distinct from
        // the title's `.text-dim` and the optional formula's `.text-ink`) —
        // the title alone is never empty (it's the column's short name), so
        // asserting on the whole tooltip's textContent would stay green even
        // with an empty `body` in `COLUMN_DEFS`.
        const body = tooltip.querySelector(".text-body");
        expect(body, "tooltip renders a body span").toBeTruthy();
        expect(body!.textContent?.trim().length ?? 0).toBeGreaterThan(0);
        fireEvent.mouseLeave(trigger);
      }
    });

    it("never ships a tooltip trigger with an empty definition body — Owners ledger", () => {
      render(
        <DraftBoard
          leagueId="lg"
          board={{ ...base, graded: true, owners: [{ ...base.owners[0], adp_total_delta: -11 }] }}
        />,
      );
      const owners = screen.getByTestId("draft-owners-desktop");
      const triggers = within(owners).getAllByRole("button", { name: /^info:/ });
      expect(triggers.length).toBeGreaterThan(0);
      for (const trigger of triggers) {
        fireEvent.mouseEnter(trigger);
        const tooltip = screen.getByRole("tooltip");
        // Scope to the BODY span specifically (`.text-body`, distinct from
        // the title's `.text-dim` and the optional formula's `.text-ink`) —
        // the title alone is never empty (it's the column's short name), so
        // asserting on the whole tooltip's textContent would stay green even
        // with an empty `body` in `COLUMN_DEFS`.
        const body = tooltip.querySelector(".text-body");
        expect(body, "tooltip renders a body span").toBeTruthy();
        expect(body!.textContent?.trim().length ?? 0).toBeGreaterThan(0);
        fireEvent.mouseLeave(trigger);
      }
    });

    it("converts the ledger to raw cols strings — head and body share the same grid-template-columns style", () => {
      render(<DraftBoard leagueId="lg" board={gradedVerdictBoard} />);
      const desktop = screen.getByTestId("draft-picks-desktop");
      const rows = within(desktop).getAllByRole("row");
      // The naming tier + label tier + at least one data row, all sharing one
      // `style.gridTemplateColumns` — a class-vs-style mismatch is exactly the
      // drift this conversion retires.
      const colStyles = new Set(rows.map((r) => (r as HTMLElement).style.gridTemplateColumns).filter(Boolean));
      expect(colStyles.size).toBe(1);
      // And no leftover Tailwind grid-cols-[...] class anywhere in the table.
      expect(desktop.querySelector('[class*="grid-cols-"]')).toBeNull();
    });
  });
});

describe("Owners table — Hit/Bust rollup and the Picks suffix", () => {
  const graded = {
    ...base,
    graded: true,
    has_verdicts: true,
    // No ADP delta on either owner: `hasAdpColumns` would otherwise win the
    // template race and the Hit/Bust column would (correctly) not render.
    owners: [
      {
        ...base.owners[0], adp_total_delta: null, production_total: 1234.5,
        // PAR set on BOTH owners on purpose: a null one renders its own
        // em-dash, and the unjudged-Hit/Bust assertion below has to be able
        // to attribute the em-dash it finds.
        points_above_round: 120.5,
        // average (3) DIFFERS from bust (1) deliberately: with the two equal,
        // a cell rendering hits-and-averages prints the same "2 / 1" as one
        // rendering hits-and-busts, and the assertion below cannot tell them
        // apart. 2 + 3 + 1 = 6 judged, so `picks_made` is 6.
        hit: 2, average: 3, bust: 1, picks_made: 6,
      },
      {
        user_id: "u2", owner: { user_id: "u2", owner_name: "Bob" },
        adp_total_delta: null, graded_picks: 0, total_picks: 1,
        production_total: 900, points_above_round: -80.0,
        hit: 0, average: 0, bust: 0, picks_made: 1,
      },
    ],
  };
  const ownersTable = () => screen.getByRole("table", { name: /draft board owners/i });

  it("prints hits and busts, and an em-dash when nothing could be judged", () => {
    // Mutation this catches: rendering "0 / 0" for an unjudged owner instead
    // of the em-dash. Bob is the discriminating row — he HAS a pick and HAS
    // production, so the only thing that makes his cell an em-dash is the
    // judged-count branch. Alice's "2 / 1" pins that the cell shows hits and
    // busts (not hits and averages: her average of 1 must NOT appear).
    render(<DraftBoard leagueId="lg" board={graded} />);
    expect(within(ownersTable()).getByText("2 / 1")).toBeTruthy();
    expect(within(ownersTable()).queryByText("2 / 3")).toBeNull();  // not averages
    expect(within(ownersTable()).queryByText("2 / 3 / 1")).toBeNull();  // not a triple
    // Exactly one: Bob's. Every other cell in this fixture is populated, so a
    // second em-dash would mean a figure went missing rather than a class
    // going unjudged.
    expect(within(ownersTable()).getAllByText("—").length).toBe(1);
  });

  it("carries the Hit/Bust header with a definition tooltip", () => {
    render(<DraftBoard leagueId="lg" board={graded} />);
    const header = labelHeaders(ownersTable())
      .find((h) => /hit\/bust/i.test(h.textContent ?? ""));
    expect(header, "the Owners table renders a Hit/Bust header").toBeTruthy();
    // Every non-identity column carries a definition trigger.
    expect(infoTriggers(header!).length).toBe(1);
  });

  it("says how many picks each owner made, in the owner cell", () => {
    // Mutation this catches: pluralising unconditionally ("1 picks"), or
    // reading `total_picks` (the SCORED denominator, 1 for Alice) instead of
    // `picks_made` (4). Alice and Bob differ on both count and plural.
    render(<DraftBoard leagueId="lg" board={graded} />);
    expect(within(ownersTable()).getByText("6 picks")).toBeTruthy();
    expect(within(ownersTable()).getByText("1 pick")).toBeTruthy();
  });

  it("drops the Hit/Bust column when the class carries ADP figures instead", () => {
    // The deliberate width trade — see OWNER_GRID_GRADED_VERDICT's docstring.
    // Without it the header would render a tenth cell into a template with
    // nine tracks and slide every later column one place left.
    render(<DraftBoard leagueId="lg" board={{
      ...graded,
      owners: graded.owners.map((o) => ({ ...o, adp_total_delta: -11 })),
    }} />);
    expect(labelHeaders(ownersTable())
      .some((h) => /hit\/bust/i.test(h.textContent ?? ""))).toBe(false);
  });

  it("sorts by hits, and sorts an unjudged owner as ungraded rather than as zero", () => {
    // THREE owners, because two cannot discriminate either half of this.
    // Descending is the first click on a numeric column, and with only Alice
    // (2 hits) and unjudged Bob, descending puts Alice first under EVERY
    // implementation — including one that ignores the column entirely. Carol
    // (5 hits) is what makes the descending order a fact about hits.
    //
    // The second click (ascending) is what pins the null: unjudged sorts LAST
    // in both directions (`draft-sort.ts`), so ascending must read
    // Alice(2) · Carol(5) · Bob(unjudged). Read `hit_bust` as 0 instead of
    // null and Bob leads the ascending sort — the mutation this exists for.
    const three = {
      ...graded,
      owners: [
        ...graded.owners,
        {
          user_id: "u3", owner: { user_id: "u3", owner_name: "Carol" },
          adp_total_delta: null, graded_picks: 5, total_picks: 7,
          production_total: 2000, points_above_round: 300.0,
          hit: 5, average: 1, bust: 1, picks_made: 7,
        },
      ],
    };
    render(<DraftBoard leagueId="lg" board={three} />);
    const header = labelHeaders(ownersTable())
      .find((h) => /hit\/bust/i.test(h.textContent ?? ""))!;
    const button = within(header).getByRole("button", { name: /hit\/bust/i });
    const order = () => within(ownersTable()).getAllByRole("row")
      .map((r) => r.textContent ?? "")
      .filter((t) => /Alice|Bob|Carol/.test(t))
      .map((t) => (/Alice/.test(t) ? "Alice" : /Bob/.test(t) ? "Bob" : "Carol"));

    fireEvent.click(button);   // descending — most hits first
    expect(order()).toEqual(["Carol", "Alice", "Bob"]);
    fireEvent.click(button);   // ascending — fewest hits first, unjudged STILL last
    expect(order()).toEqual(["Alice", "Carol", "Bob"]);
  });
});

describe("Hit/Bust on the mobile owner card", () => {
  /** Below 910px the desktop Owners table is not rendered at all, so this card
   *  is the ONLY place the rollup is reachable — a figure that exists only in
   *  the hidden table is a figure a phone user never sees. */
  const card = () => {
    const mobile = screen.getByTestId("draft-picks-mobile");
    return within(mobile).getByRole("button", { name: /Alice/ })
      .parentElement as HTMLElement;
  };
  const owner = (over: Record<string, unknown>) => ({
    ...base.owners[0], adp_total_delta: null, production_total: 500,
    points_above_round: 40, ...over,
  });

  it("carries the counts the desktop column carries", () => {
    render(<DraftBoard leagueId="lg" board={{
      ...base, graded: true, has_verdicts: true,
      owners: [owner({ hit: 2, average: 3, bust: 1, picks_made: 6 })],
    }} />);
    expect(within(card()).getByText("Hit/Bust")).toBeTruthy();
    // Hits and busts — not the average (3), which is why it differs from bust.
    expect(within(card()).getByText("2 / 1")).toBeTruthy();
  });

  it("omits it entirely when nothing in the owner's class could be judged", () => {
    // Mutation this catches: dropping the judged-count guard, so an owner
    // whose class has no verdicts gets a "Hit/Bust 0 / 0" fact. The owner is
    // otherwise fully graded here — real production, a real PAR — so the only
    // thing that can omit the row is the guard itself.
    render(<DraftBoard leagueId="lg" board={{
      ...base, graded: true, has_verdicts: true,
      owners: [owner({ hit: 0, average: 0, bust: 0, picks_made: 2 })],
    }} />);
    expect(within(card()).queryByText("Hit/Bust")).toBeNull();
  });

  it("omits it when the board carries no verdicts at all", () => {
    render(<DraftBoard leagueId="lg" board={{
      ...base, graded: true, has_verdicts: false,
      owners: [owner({ hit: 2, average: 3, bust: 1, picks_made: 6 })],
    }} />);
    expect(within(card()).queryByText("Hit/Bust")).toBeNull();
  });
});
