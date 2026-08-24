import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DraftGoingIn } from "@/components/DraftGoingIn";
import { DraftBoard } from "@/components/DraftBoard";
import type { DraftBoardOwner, DraftBoardResp } from "@/lib/types";

const OWNERS: DraftBoardOwner[] = [
  { user_id: "u1", owner: { user_id: "u1", owner_name: "Mikey" }, graded_picks: 0, total_picks: 0, production_total: 0 },
  { user_id: "u2", owner: { user_id: "u2", owner_name: "Dan" }, graded_picks: 0, total_picks: 0, production_total: 0 },
  { user_id: "u3", owner: { user_id: "u3", owner_name: "Sam" }, graded_picks: 0, total_picks: 0, production_total: 0 },
];

const BOARD: DraftBoardResp = {
  league_id: "lg", season: 2026, seasons: [2026], format: "dynasty",
  graded: false,
  baseline_label: "",
  picks: [],
  owners: [],
  needs: [
    {
      user_id: "u1", holes: ["QB"], drafted_into: ["QB"], started: 1, drafted_into_count: 1,
      production: 22.6,
      slots: [{ slot: "QB", position: "QB", margin: -20, is_hole: true, vetoed: false }],
    },
  ],
};

describe("DraftGoingIn", () => {
  it("closes Positions Drafted with the owner's total picks, set off from the position rows", () => {
    render(
      <DraftGoingIn
        owners={[
          { user_id: "u1", owner: { user_id: "u1", owner_name: "Joey" }, graded_picks: 0, total_picks: 7, production_total: 0 },
        ]}
        needs={[{
          user_id: "u1", holes: ["WR", "WR", "RB"], drafted_into: ["WR", "WR", "RB"],
          started: 0, drafted_into_count: 3, production: 14.2,
          slots: [
            { slot: "WR", position: "WR", margin: -35, is_hole: true, vetoed: false },
            { slot: "WR_2", position: "WR", margin: -27, is_hole: true, vetoed: false },
            { slot: "RB", position: "RB", margin: -32, is_hole: true, vetoed: false },
          ],
        }]}
      />,
    );
    const cell = screen.getByTestId("going-in-drafted-u1");
    expect(cell).toHaveTextContent("7 total picks");
    expect(cell).toHaveTextContent("WR");
    expect(cell).toHaveTextContent("2/2");
  });

  it("renders Points Produced as a real figure, distinct from a dash when nothing was credited", () => {
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[
          {
            user_id: "u1", holes: ["RB"], drafted_into: ["RB"], started: 0,
            drafted_into_count: 1, production: 14.2,
            slots: [{ slot: "RB", position: "RB", margin: -32, is_hole: true, vetoed: false }],
          },
          {
            user_id: "u2", holes: [], drafted_into: [], started: 0,
            drafted_into_count: 0, production: 0,
            slots: [{ slot: "WR", position: "WR", margin: 2, is_hole: false, vetoed: false }],
          },
        ]}
      />,
    );
    expect(screen.getByTestId("going-in-points-u1")).toHaveTextContent("14.2");
    expect(screen.getByTestId("going-in-points-u2")).toHaveTextContent("—");
  });

  it("renders a real 0.0 Points Produced distinctly from the em-dash — a credited pick that produced nothing is not the same as nothing credited", () => {
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u1", holes: ["RB"], drafted_into: ["RB"], started: 0,
          drafted_into_count: 1, production: 0,
          slots: [{ slot: "RB", position: "RB", margin: -32, is_hole: true, vetoed: false }],
        }]}
      />,
    );
    const cell = screen.getByTestId("going-in-points-u1");
    expect(cell).toHaveTextContent("0.0");
    expect(cell).not.toHaveTextContent("—");
  });

  it("still renders a needs row for an owner absent from the name-lookup list, falling back to the raw id", () => {
    // Catches: filtering `needs` down to only the user_ids present in
    // `owners` (the gradeable-drafters set). `engine/draft_needs.py` emits
    // one entry per owner in the league's CURRENT rosters, which is a wider
    // set than `board.owners` — an owner with no gradeable pick this class
    // still has a roster and still gets a needs verdict.
    render(
      <DraftGoingIn
        owners={[]}
        needs={[{
          user_id: "u9", holes: [], drafted_into: [], started: 0, drafted_into_count: 0,
          production: 0, slots: [],
        }]}
      />,
    );
    expect(screen.getAllByText("u9").length).toBeGreaterThan(0);
    expect(screen.getByTestId("going-in-needs-u9")).toBeTruthy();
  });

  it("never colours the drafted-into or points-produced cells across multiple owners — colour stays inside Biggest Needs only", () => {
    // Catches: a `-pos`/`-neg`/`-warn` tone class landing on the "Positions
    // Drafted" or "Points Produced" cell, e.g. treating "has holes" or a
    // vetoed softest slot as a negative-toned result. Updated from this
    // test's original all-or-nothing assertion (zero `.text-neg-strong`
    // ANYWHERE in the container), which stopped being true the moment
    // `BiggestNeeds`' severity phrases started colouring their own 2-3 word
    // clause on purpose (see that component's header comment) — the real
    // invariant was never "no colour anywhere", it was "no colour outside
    // Biggest Needs", so every hit is now required to trace back to a
    // `going-in-needs-*` cell instead of being banned outright.
    const { container } = render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[
          {
            user_id: "u1", holes: ["QB", "TE"], drafted_into: ["TE"], started: 1, drafted_into_count: 1,
            production: 5.0,
            slots: [
              { slot: "QB", position: "QB", margin: -30, is_hole: true, vetoed: false },
              { slot: "TE", position: "TE", margin: -12, is_hole: true, vetoed: false },
            ],
          },
          {
            user_id: "u3", holes: [], drafted_into: [], started: 0, drafted_into_count: 0,
            production: 0,
            slots: [{ slot: "QB", position: "QB", margin: -79, is_hole: false, vetoed: true }],
          },
        ]}
      />,
    );
    const stray = container.querySelectorAll(".text-neg-strong, .text-warn-strong");
    for (const el of Array.from(stray)) {
      expect(el.closest("[data-testid^='going-in-needs-']")).not.toBeNull();
    }
  });

  it("drives both the desktop table and the mobile cards from the same needs array", () => {
    // Catches: the mobile reflow reading a stale/undefined prop and silently
    // rendering nothing (or a different owner set) while the desktop table
    // looks correct — the two bodies must always agree.
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u1", holes: ["QB"], drafted_into: ["QB"], started: 1, drafted_into_count: 1,
          production: 22.6,
          slots: [{ slot: "QB", position: "QB", margin: -20, is_hole: true, vetoed: false }],
        }]}
      />,
    );
    const desktop = screen.getByTestId("draft-going-in-desktop");
    const mobile = screen.getByTestId("draft-going-in-mobile");
    expect(within(desktop).getAllByText("Mikey").length).toBeGreaterThan(0);
    expect(within(mobile).getAllByText("Mikey").length).toBeGreaterThan(0);
    // Positions Drafted's "1/1 drafted" fraction row is now shared logic
    // (`PositionsDrafted`), not the retired inlined `started`/
    // `drafted_into_count` mobile fraction — both bodies must render it.
    expect(desktop.textContent).toContain("1/1");
    expect(mobile.textContent).toContain("1/1 drafted");
    // The `QB-20` chip format is retired (`formatMargin`); Biggest Needs now
    // renders a severity sentence naming the position in bold, in both
    // layouts.
    expect(desktop.textContent).toContain("QB");
    expect(mobile.textContent).toContain("QB");
  });

  it("renders every needs sentence, drafted group, and the points figure inside the mobile card too", () => {
    render(
      <DraftGoingIn
        owners={[
          { user_id: "u1", owner: { user_id: "u1", owner_name: "Joey" }, graded_picks: 0, total_picks: 7, production_total: 0 },
        ]}
        needs={[{
          user_id: "u1", holes: ["RB"], drafted_into: ["RB"], started: 0,
          drafted_into_count: 1, production: 14.2,
          slots: [{ slot: "RB", position: "RB", margin: -32, is_hole: true, vetoed: false }],
        }]}
      />,
    );
    const mobile = screen.getByTestId("draft-going-in-mobile");
    // `getAllByText`, not the brief's literal `getByText` — "RB" legitimately
    // appears twice inside one mobile card (Biggest Needs' bold position
    // label AND Positions Drafted's own "RB" group label), so a single-match
    // query throws "found multiple elements" here. The intent survives:
    // confirm at least one "RB" node exists and that it lives inside the
    // mobile card.
    const rbMatches = within(mobile).getAllByText(/RB/);
    expect(rbMatches.length).toBeGreaterThan(0);
    expect(rbMatches[0].closest("[data-testid='draft-going-in-mobile']")).not.toBeNull();
    expect(within(mobile).getByText(/7 total picks/)).toBeTruthy();
    expect(within(mobile).getByText(/14\.2/)).toBeTruthy();
  });

  it("renders nothing for an empty (but non-null) needs list", () => {
    // Catches: dropping this defensive guard and rendering a header over an
    // empty ledger, matching the desktop Owners section's own "results
    // only, no grade" precedent for an empty array.
    const { container } = render(<DraftGoingIn owners={OWNERS} needs={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders one sentence per hole instance, never merging two holes at one position", () => {
    // Defect this catches (spec: "Defects found during mockup, not
    // assumed"): an earlier draft summarized "Both your RBs were a full
    // tier below a startable player" for two holes with very different
    // margins (-41 and -21 -- Deep and Wide respectively). That is wrong
    // for the milder one. Each hole instance must get its own line.
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u1", holes: ["RB"], drafted_into: [], started: 0,
          drafted_into_count: 0, production: 0,
          slots: [
            { slot: "RB", position: "RB", margin: -41, is_hole: true, vetoed: false },
            { slot: "RB_2", position: "RB", margin: -21, is_hole: true, vetoed: false },
          ],
        }]}
      />,
    );
    const cell = screen.getByTestId("going-in-needs-u1");
    expect(cell).toHaveTextContent("weaker");
    expect(cell).toHaveTextContent("other");
    // Two DISTINCT sentences must be present -- not one merged line.
    const lines = cell.querySelectorAll("[data-testid='going-in-need-line']");
    expect(lines.length).toBe(2);
  });

  it("never claims a milder hole is the 'deepest' when a worse sibling hole exists at the same position", () => {
    // Defect this catches (final-review finding 1): the `deep` tier's third
    // phrase variant used to read "was your deepest need at that spot" -- a
    // UNIQUENESS claim, unlike every other phrase in NEED_PHRASES, which
    // describe a LEVEL. With two holes at one position both in the deep tier
    // (|margin| >= 40), the milder ("other") instance could land on that
    // variant while the worse ("weaker") instance sat on a different line,
    // producing a direct contradiction between adjacent sentences. Margins
    // -60/-44 reproduce exactly that: both deep tier, and -44 % 3 === 2 hits
    // the old "deepest" wording on the non-worst instance. This would have
    // failed before the phrase was reworded and must pass after.
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u1", holes: ["RB"], drafted_into: [], started: 0,
          drafted_into_count: 0, production: 0,
          slots: [
            { slot: "RB", position: "RB", margin: -60, is_hole: true, vetoed: false },
            { slot: "RB_2", position: "RB", margin: -44, is_hole: true, vetoed: false },
          ],
        }]}
      />,
    );
    const cell = screen.getByTestId("going-in-needs-u1");
    expect(cell).toHaveTextContent("weaker");
    expect(cell).toHaveTextContent("other");
    expect(cell.textContent).not.toContain("deepest");
  });

  it("bolds only the position label, never the whole sentence", () => {
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u1", holes: ["QB"], drafted_into: [], started: 0,
          drafted_into_count: 0, production: 0,
          slots: [{ slot: "QB", position: "QB", margin: -97, is_hole: true, vetoed: false }],
        }]}
      />,
    );
    const cell = screen.getByTestId("going-in-needs-u1");
    const bold = cell.querySelector("b");
    expect(bold).not.toBeNull();
    expect(bold!.textContent).toBe("QB");
  });

  it("colours only a 2-3 word severity phrase, using the Deep tier for a margin of 40+", () => {
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u1", holes: ["QB"], drafted_into: [], started: 0,
          drafted_into_count: 0, production: 0,
          slots: [{ slot: "QB", position: "QB", margin: -97, is_hole: true, vetoed: false }],
        }]}
      />,
    );
    const cell = screen.getByTestId("going-in-needs-u1");
    const highlight = cell.querySelector(".text-neg-strong");
    expect(highlight).not.toBeNull();
    // The highlight is 2-3 words, not the whole sentence.
    expect(highlight!.textContent!.trim().split(/\s+/).length).toBeLessThanOrEqual(3);
    expect(cell.textContent).not.toContain("QB-97");
    expect(cell.textContent).not.toContain("-97");
  });

  it("uses the Wide tier (amber) for a margin between 20 and 39, and Thin (dim) under 20", () => {
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u1", holes: ["RB", "WR"], drafted_into: [], started: 0,
          drafted_into_count: 0, production: 0,
          slots: [
            { slot: "RB", position: "RB", margin: -25, is_hole: true, vetoed: false },
            { slot: "WR", position: "WR", margin: -5, is_hole: true, vetoed: false },
          ],
        }]}
      />,
    );
    const cell = screen.getByTestId("going-in-needs-u1");
    expect(cell.querySelector(".text-warn-strong")).not.toBeNull();
    expect(cell.querySelector(".text-dim")).not.toBeNull();
  });

  it("degrades to a full sentence for the no-holes case, naming the softest position with no number", () => {
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u3", holes: [], drafted_into: [], started: 0,
          drafted_into_count: 0, production: 0,
          slots: [{ slot: "WR", position: "WR", margin: 42, is_hole: false, vetoed: false }],
        }]}
      />,
    );
    const cell = screen.getByTestId("going-in-needs-u3");
    expect(cell).toHaveTextContent("No real needs at draft");
    expect(cell).toHaveTextContent("WR");
    expect(cell.textContent).not.toMatch(/[+-]\d/); // no raw signed number anywhere
  });

  describe("via DraftBoard", () => {
    it("omits the panel entirely when needs is null", () => {
      // Catches: rendering an empty/broken panel instead of omitting it —
      // `needs: null` is the common case (redraft leagues, first-season
      // startup dynasty, and every non-newest season on the selector).
      render(<DraftBoard leagueId="1" board={{ ...BOARD, needs: null }} />);
      expect(screen.queryByTestId("draft-going-in")).toBeNull();
    });

    it("renders the panel when needs is present", () => {
      // Catches: DraftBoard never wiring DraftGoingIn in at all, or gating
      // it on the wrong field (e.g. `board.graded`).
      render(<DraftBoard leagueId="1" board={BOARD} />);
      expect(screen.getByTestId("draft-going-in")).toBeTruthy();
    });

    it("places the panel before the picks table in DOM order", () => {
      // Catches: the panel sitting after Picks again (its original,
      // unfindable position — 36 picks below it) — a regression this whole
      // task exists to fix. `compareDocumentPosition` checks actual DOM
      // order, not just that both elements are present.
      render(<DraftBoard leagueId="1" board={BOARD} />);
      const goingIn = screen.getByTestId("draft-going-in");
      const picksDesktop = screen.getByTestId("draft-picks-desktop");
      // eslint-disable-next-line no-bitwise
      const relation = goingIn.compareDocumentPosition(picksDesktop);
      expect(relation & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
  });
});

describe("Going in row order", () => {
  /** The panel sits directly under the Owners table and lists the same
   *  people. On the reference league the two orders shared no position at
   *  all — the engine emits in Sleeper roster order, the table sorts by
   *  Points Above Round. */
  const needsFor = (ids: string[]) =>
    ids.map((user_id) => ({
      user_id, holes: [], drafted_into: [], started: 0, drafted_into_count: 0,
      production: 0,
      slots: [{ slot: "QB", position: "QB", margin: 5, is_hole: false, vetoed: false }],
    }));
  const namesInOrder = () =>
    within(screen.getByTestId("draft-going-in-desktop"))
      .getAllByRole("row")
      .slice(1)  // drop the header row
      .map((r) => (r.textContent ?? "").match(/Mikey|Dan|Sam|Ghost/)?.[0] ?? "");

  it("follows the owners array, not the order the engine emitted", () => {
    // Mutation this catches: rendering `needs` directly. The needs array is
    // deliberately the EXACT REVERSE of `owners` — with the two merely
    // rotated, or sharing any fixed point, a component that ignored `owners`
    // could still land on a passing order by luck.
    render(<DraftGoingIn needs={needsFor(["u3", "u2", "u1"])} owners={OWNERS} />);
    expect(namesInOrder()).toEqual(["Mikey", "Dan", "Sam"]);
  });

  it("re-orders when the owners array is re-sorted", () => {
    // The table above is user-sortable, so this order has to follow it rather
    // than being a one-time arrangement.
    const resorted = [OWNERS[2], OWNERS[0], OWNERS[1]];
    render(<DraftGoingIn needs={needsFor(["u1", "u2", "u3"])} owners={resorted} />);
    expect(namesInOrder()).toEqual(["Sam", "Mikey", "Dan"]);
  });

  it("keeps an owner the table doesn't carry, at the end", () => {
    // Mutation this catches: filtering `needs` down to `owners` (dropping the
    // row), or sorting the unknown to the FRONT via a `?? -1` default.
    // `needs` is the wider set — one entry per owner with a roster, where
    // `board.owners` is gradeable drafters only — and an owner who made no
    // gradeable pick still went into the draft with a lineup.
    render(<DraftGoingIn needs={needsFor(["ghost", "u2", "u1"])} owners={OWNERS} />);
    const rows = namesInOrder();
    expect(rows.slice(0, 2)).toEqual(["Mikey", "Dan"]);
    expect(rows).toHaveLength(3);
    // Unmatched owners fall back to the raw id, which is the existing
    // `nameOf.get(...) ?? n.user_id` behaviour.
    expect(within(screen.getByTestId("draft-going-in-desktop"))
      .getByText("ghost")).toBeTruthy();
  });

  it("orders the mobile cards from the same array", () => {
    // The desktop table is not rendered below 910px, so a phone reader sees
    // ONLY these cards — ordering one and not the other would leave the
    // narrow layout permanently in engine order.
    render(<DraftGoingIn needs={needsFor(["u3", "u2", "u1"])} owners={OWNERS} />);
    const order = (screen.getByTestId("draft-going-in-mobile").textContent ?? "");
    for (const n of ["Mikey", "Dan", "Sam"]) expect(order).toContain(n);
    expect(order.indexOf("Mikey")).toBeLessThan(order.indexOf("Dan"));
    expect(order.indexOf("Dan")).toBeLessThan(order.indexOf("Sam"));
  });
});
