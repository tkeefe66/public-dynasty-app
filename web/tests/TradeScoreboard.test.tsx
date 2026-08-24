import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeScoreboard } from "@/components/TradeScoreboard";
import type { LensMargins, LensWinners, TradeSideView } from "@/lib/types";

/** The fixture must be SELF-CONSISTENT: every margin has to be derivable from
 *  the two sides' realized breakdown rows, because that is exactly the
 *  relationship the component draws (margin figure vs bar scaled by the pot).
 *
 *  It was not. `playoff` carried a margin of 96 while BOTH sides had
 *  `production_playoff: 0`, so the pot was 0 and that row rendered an empty
 *  track beside "+96.0" — a figure/bar contradiction sitting green in the
 *  suite. Unreachable in production (an all-zero lens arrives unscored, as
 *  null) but the test could not have caught it if it were. */
function side(
  user_id: string, owner_name: string, ktc: number, pts: number, playoff = 0,
): TradeSideView {
  return {
    user_id, owner_name, received: [], given: [],
    snapshot_ktc_swing: 0, received_ktc: ktc,
    production_total: pts, production_regular: pts,
    production_playoff: playoff, production_toilet: 0,
    breakdown: [
      {
        label: `${owner_name} haul`, kind: "player", player_id: `p_${user_id}`, ktc,
        production_total: pts, production_regular: pts,
        production_playoff: playoff, production_toilet: 0,
        production_started: pts, terminal_state: "on_roster",
      },
    ],
    production_started: pts, start_pct: 1,
    at_trade_ktc_swing: null, aged_ktc_swing: null,
    at_trade_approx: false, at_trade_snapshot_date: null,
  } as unknown as TradeSideView;
}

// Playoff: Cavanaugh 136 vs Reznik 40 → margin 96 to u2, pot 176. Consistent.
const SIDES = [
  side("u1", "Reznik", 9000, 700, 40),
  side("u2", "Cavanaugh", 5060, 318, 136),
];

const MARGINS: LensMargins = { value: 3940, total: 382, regular: 382, playoff: 96, toilet: null };
const WINNERS: LensWinners = { value: "u1", total: "u1", regular: "u1", playoff: "u2", toilet: null };

function renderBoard(over: Partial<React.ComponentProps<typeof TradeScoreboard>> = {}) {
  return render(
    <TradeScoreboard
      margins={MARGINS}
      winners={WINNERS}
      sides={SIDES}
      call="split"
      lensTally="3-1"
      {...over}
    />,
  );
}

describe("TradeScoreboard", () => {
  it("renders the five lenses in the fixed vocabulary, in full, in fixed order", () => {
    renderBoard();
    // The desktop ledger and the narrow card list both render every lens (the
    // inactive one is hidden by CSS only) — tolerate both being in the DOM.
    // FULL names: this column is `minmax(0,1fr)`, so there is no width excuse
    // for "Value"/"Reg"/"Toilet". "Trade Value" in particular must keep the
    // word "Trade".
    for (const label of [
      "Trade Value", "Total Points", "Regular Season Points",
      "Playoff Points", "Toilet Bowl Points",
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("draws each bar as the margin's share of the pot, and none for an unscored lens", () => {
    const { container } = renderBoard();
    // Bars are the only elements carrying an inline width%.
    const widths = Array.from(container.querySelectorAll<HTMLElement>("[style*='width']"))
      .map((el) => el.style.width)
      .filter(Boolean);

    // Four scored lenses × two breakpoints = 8 bars. `toilet` is null and must
    // draw nothing at all — an empty track, not a zero-length fill.
    expect(widths.length).toBe(8);

    // value: 3940 / (9000 + 5060) = 28.02%
    expect(widths).toContain(`${(3940 / 14060) * 100}%`);
    // playoff: 96 / (40 + 136) = 54.55% — the row whose fixture used to be
    // impossible. Now it is derivable from the two sides' own rows.
    expect(widths).toContain(`${(96 / 176) * 100}%`);
  });

  it("uses UNSIGNED bars — every margin is top-minus-runner-up, so never negative", () => {
    const { container } = renderBoard();
    // A signed Bar draws a centre line (`bg-rule-strong`) and caps its fill at
    // 50% of the track. Margins can never be negative, so a diverging axis
    // would leave half the column permanently dead.
    expect(container.querySelector(".bg-rule-strong")).toBeNull();
    expect(container.querySelector(".bg-neg-bar")).toBeNull();
    for (const w of Array.from(container.querySelectorAll<HTMLElement>("[style*='width']"))) {
      expect(parseFloat(w.style.width)).toBeLessThanOrEqual(100);
    }
  });

  it("renders signed margins with the sign always shown", () => {
    renderBoard();
    expect(screen.getAllByText("+3,940").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+382.0").length).toBeGreaterThan(0);
  });

  it("renders a dash, not zero, for an unscored (null) lens and claims no winner", () => {
    renderBoard();
    // Two per breakpoint: the margin figure and the winner cell.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("names the winner of each decided lens", () => {
    renderBoard();
    expect(screen.getAllByText("Reznik").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Cavanaugh").length).toBeGreaterThan(0);
  });

  it("keeps the drawn column contract identical on the head row and every body row", () => {
    const { container } = renderBoard();
    const grids = Array.from(container.querySelectorAll<HTMLElement>("[style*='grid-template-columns']"));
    expect(grids.length).toBe(6); // head + five lenses
    // What matters is that ONE string reaches all six — a head/body mismatch
    // is the most common ledger bug. The literal is asserted too, but the
    // winner track is 150px, not the template's 96px: `Trade.dc.html` sizes
    // its columns around the fixture name "Reznik", and at 96px a real
    // Sleeper name rendered as "ChocGummyBe…".
    const tracks = new Set(grids.map((g) => g.style.gridTemplateColumns));
    expect([...tracks]).toEqual(["minmax(0,1fr) 96px 130px 150px"]);
  });

  it("never renders the banned term", () => {
    const { container } = renderBoard();
    expect(container.textContent).not.toMatch(/KTC/);
  });
});

describe("the section head carries no scope note", () => {
  /* `tallyKicker` and the mono line it fed are DELETED, not hidden. The head
     used to restate the ledger's own verdict a few pixels above it ("Five
     lenses · 3-1 to Reznik") — the rows below say the same thing and are the
     figure that reconciles. `SectionHeader` no longer accepts a `note` prop at
     all, so a regression is a type error rather than something this test has to
     catch; these two assertions only pin the rendered result. */
  it("renders the title alone", () => {
    renderBoard();
    expect(screen.getByText("Scoreboard")).toBeInTheDocument();
    expect(screen.queryByText(/Five lenses/i)).not.toBeInTheDocument();
  });
});
