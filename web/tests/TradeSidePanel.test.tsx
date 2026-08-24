import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeSidePanel } from "@/components/TradeSidePanel";
import type { LensMargins, LensWinners } from "@/lib/types";

const side = {
  user_id: "u1", owner_name: "Mike", team_name: "Team", avatar_url: undefined,
  received: [], given: [{ name: "Adams", player_id: "p_a" }],
  snapshot_ktc_swing: 1840, received_ktc: 7500,
  production_total: 41.2, production_regular: 30, production_playoff: 9, production_toilet: 5,
  breakdown: [
    { label: "Bijan", kind: "player", player_id: "p_b", ktc: 7500,
      production_total: 41.2, production_regular: 30, production_playoff: 9, production_toilet: 5,
      production_started: 35.0, terminal_state: "on_roster" },
  ],
  production_started: 35.0,
  start_pct: 0.85,
  at_trade_ktc_swing: 1500, aged_ktc_swing: 340,
  at_trade_approx: false, at_trade_snapshot_date: null,
} as any;

const winnersByLens: LensWinners = { value: "u1", total: "u1", regular: "u1", playoff: null, toilet: null };
const marginsByLens: LensMargins = { value: 100, total: 10, regular: 10, playoff: null, toilet: null };

describe("TradeSidePanel", () => {
  it("renders the owner and a received-player stat row", () => {
    render(
      <TradeSidePanel
        side={side}
        winnersByLens={winnersByLens}
        marginsByLens={marginsByLens}
        call="unanimous"
      />,
    );
    expect(screen.getByText("Mike")).toBeTruthy();
    expect(screen.getAllByText("Bijan").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/7,500/).length).toBeGreaterThan(0);
  });

  it("tags the received player ON ROSTER", () => {
    render(
      <TradeSidePanel
        side={side}
        winnersByLens={winnersByLens}
        marginsByLens={marginsByLens}
        call="unanimous"
      />,
    );
    // Desktop grid renders the tag once; mobile rules duplicate it (mobile
    // hidden via CSS, same convention as TradeStatTable.test.tsx).
    expect(screen.getAllByText("ON ROSTER").length).toBeGreaterThan(0);
  });

  it("says 'Ahead on value', not 'Prevailed'/'Lost', when one lens decided it", () => {
    // `call` is "unanimous" off a single decided lens whenever nobody has
    // played — the four production lenses are 0 both sides and unscored.
    const oneLens = { value: side.user_id, total: null, regular: null, playoff: null, toilet: null };
    const { container } = render(
      <TradeSidePanel
        side={side}
        winnersByLens={oneLens as typeof winnersByLens}
        marginsByLens={{ value: 633, total: null, regular: null, playoff: null, toilet: null }}
        call="unanimous"
      />,
    );
    expect(container.textContent).toContain("Ahead on value");
    expect(container.textContent).not.toContain("Prevailed");
  });

  it("says nothing at all for the side that is merely behind on one lens", () => {
    // Not "Lost" — one lens is not a loss, and a side is not required to have
    // a verdict word.
    const oneLens = { value: "somebody-else", total: null, regular: null, playoff: null, toilet: null };
    const { container } = render(
      <TradeSidePanel
        side={side}
        winnersByLens={oneLens as typeof winnersByLens}
        marginsByLens={{ value: 633, total: null, regular: null, playoff: null, toilet: null }}
        call="unanimous"
      />,
    );
    expect(container.textContent).not.toContain("Lost");
    expect(container.textContent).not.toContain("Ahead on");
  });

  it("does NOT restate what the side gave", () => {
    render(
      <TradeSidePanel
        side={side}
        winnersByLens={winnersByLens}
        marginsByLens={marginsByLens}
        call="unanimous"
      />,
    );
    // The panel used to close with a `for <given>` exchange line. It was
    // removed because it is always a restatement: one side's GIVEN is another
    // side's RECEIVED, and the trade page renders every side — so that line
    // repeated the panel directly above or below it. Same reasoning that
    // removed the one-row became subtotal.
    expect(screen.queryByText("for")).toBeNull();
  });

  it("links the owner name to the franchise page when leagueId is given", () => {
    render(
      <TradeSidePanel
        side={side}
        winnersByLens={winnersByLens}
        marginsByLens={marginsByLens}
        call="unanimous"
        leagueId="L9"
      />,
    );
    const link = screen.getByRole("link", { name: /Mike/i });
    expect(link).toHaveAttribute("href", "/league/L9/owner/u1");
  });

  it("renders the owner as plain text without a leagueId", () => {
    render(
      <TradeSidePanel
        side={side}
        winnersByLens={winnersByLens}
        marginsByLens={marginsByLens}
        call="unanimous"
      />,
    );
    expect(screen.queryByRole("link", { name: /Mike/i })).toBeNull();
  });

  it("shows 'Prevailed' when this side won the call", () => {
    render(
      <TradeSidePanel
        side={side}
        winnersByLens={winnersByLens}
        marginsByLens={marginsByLens}
        call="unanimous"
      />,
    );
    expect(screen.getByText("Prevailed")).toBeTruthy();
  });

  it("shows 'Lost' when the other side won the call", () => {
    const losingWinners: LensWinners = { value: "u2", total: "u2", regular: "u2", playoff: null, toilet: null };
    render(
      <TradeSidePanel
        side={side}
        winnersByLens={losingWinners}
        marginsByLens={marginsByLens}
        call="unanimous"
      />,
    );
    expect(screen.getByText("Lost")).toBeTruthy();
  });

  it("renders no status word for a 'none' call", () => {
    const noWinners: LensWinners = { value: null, total: null, regular: null, playoff: null, toilet: null };
    render(
      <TradeSidePanel
        side={side}
        winnersByLens={noWinners}
        marginsByLens={{ value: null, total: null, regular: null, playoff: null, toilet: null }}
        call="none"
      />,
    );
    expect(screen.queryByText("Prevailed")).toBeNull();
    expect(screen.queryByText("Lost")).toBeNull();
  });

  it("tags a dropped player with the week it happened", () => {
    const droppedSide = {
      ...side,
      breakdown: [
        { label: "Achane", kind: "player", player_id: "p_ach", ktc: 5820,
          production_total: 164.0, production_regular: 108.2, production_playoff: 0,
          production_toilet: 0, production_started: 108.2, terminal_state: "dropped" },
      ],
    };
    render(
      <TradeSidePanel
        side={droppedSide}
        winnersByLens={winnersByLens}
        marginsByLens={marginsByLens}
        call="unanimous"
        dropWeeks={{ p_ach: 8 }}
      />,
    );
    expect(screen.getAllByText("DROPPED WK 8").length).toBeGreaterThan(0);
  });

  /* ---- the bench-miss reading ---------------------------------------- */

  const renderPanel = (over: Record<string, unknown>) =>
    render(
      <TradeSidePanel
        side={{ ...side, ...over }}
        winnersByLens={winnersByLens}
        marginsByLens={marginsByLens}
        call="unanimous"
      />,
    );

  it("states what share of the haul was actually started", () => {
    // Computed since the trade view was written, typed all the way here, and
    // never rendered — its only consumer was the "Barely played" finding,
    // which fires only under a narrow threshold. A side that started 60% of
    // its haul was simply never told.
    renderPanel({ start_pct: 0.6 });
    expect(screen.getByText(/Started 60% of the haul/i)).toBeTruthy();
  });

  it("says nothing at all when the haul has not played", () => {
    // null, never "0%" — 0% reads as "you benched everything", the most
    // damning reading of the least information.
    renderPanel({ start_pct: null });
    expect(screen.queryByText(/of the haul/i)).toBeNull();
  });
});
