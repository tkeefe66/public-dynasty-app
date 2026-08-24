import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeFindings } from "@/components/TradeFindings";
import type { TradeSideView } from "@/lib/types";

function makeSide(
  overrides: Partial<TradeSideView> & { user_id: string; owner_name: string },
): TradeSideView {
  return {
    team_name: undefined,
    avatar_url: undefined,
    received: [],
    given: [],
    snapshot_ktc_swing: 0,
    received_ktc: 5000,
    production_total: 500,
    production_regular: 400,
    production_playoff: 100,
    production_toilet: 0,
    breakdown: [],
    production_started: 400,
    start_pct: 0.8,
    at_trade_ktc_swing: null,
    aged_ktc_swing: null,
    at_trade_approx: false,
    at_trade_snapshot_date: null,
    at_trade_standing: null,
    ...overrides,
  };
}

const mkAsset = (
  label: string,
  started: number,
  total: number,
  playoff: number,
  ktc = 0,
) => ({
  label,
  kind: "player" as const,
  player_id: label,
  ktc,
  production_total: total,
  production_regular: total - playoff,
  production_playoff: playoff,
  production_toilet: 0,
  production_started: started,
  terminal_state: "on_roster" as const,
});

// A received asset that got flipped away — the realized (flip-aware) figures
// live on `flip.became`, NOT on the row's own `ktc`/production fields (those
// describe the asset as originally received, before it moved on).
const mkFlipped = (
  label: string,
  becameKtc: number,
  becameStarted: number,
  becameTotal: number,
  becamePlayoff: number,
) => ({
  label,
  kind: "player" as const,
  player_id: label,
  ktc: 9999999, // deliberately nonsense — must never be read once `flip` is set
  production_total: 9999999,
  production_regular: 9999999,
  production_playoff: 9999999,
  production_toilet: 0,
  production_started: 9999999,
  terminal_state: "on_roster" as const,
  flip: {
    to_owner: "Other Owner",
    trade_id: "t2",
    league_id: "L1",
    date: "2024-06-01",
    became: [
      {
        label: `${label} (became)`,
        kind: "player" as const,
        player_id: `${label}-became`,
        ktc: becameKtc,
        production_total: becameTotal,
        production_regular: becameTotal - becamePlayoff,
        production_playoff: becamePlayoff,
        production_toilet: 0,
        production_started: becameStarted,
        terminal_state: "on_roster" as const,
      },
    ],
  },
});

describe("TradeFindings", () => {
  it("renders three derived stats with a mono figure and a one-line sentence", () => {
    const winner = makeSide({
      // received_ktc is the raw at-trade swing; the breakdown row's own ktc
      // (9998, no flip) is what realizedTotals actually sums, and the two
      // deliberately agree here since nothing on this side was flipped.
      user_id: "u1", owner_name: "Mikey", received_ktc: 9998, production_started: 705,
      breakdown: [mkAsset("Bijan Robinson", 705, 705, 118, 9998)],
    });
    const loser = makeSide({
      user_id: "u2", owner_name: "Tom", received_ktc: 1000, production_started: 300,
      breakdown: [mkAsset("Nick Chubb", 300, 424, 0, 1000)],
    });
    render(<TradeFindings sides={[winner, loser]} winner_user_id="u1" />);
    expect(screen.getByText("Findings")).toBeTruthy();
    // single-piece dominance: Bijan (705 started) > Tom's whole return (300)
    expect(screen.getByText(/alone outscored Tom's entire return/i)).toBeTruthy();
    // playoff swing: 118 vs 0
    expect(screen.getByText(/on playoff points/i)).toBeTruthy();
    // value multiple: realized ktc 9998 vs 1000, no flip so it matches received_ktc
    expect(screen.getByText(/worth 10\.0 times Tom's today/i)).toBeTruthy();
  });

  it("renders nothing when there is no winner to derive findings from", () => {
    const a = makeSide({ user_id: "u1", owner_name: "Mikey" });
    const b = makeSide({ user_id: "u2", owner_name: "Tom" });
    const { container } = render(<TradeFindings sides={[a, b]} winner_user_id={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("bases the value-multiple and sweep claims on realized (flip-aware) totals, not the raw received_ktc swing", () => {
    // Mikey's headline received_ktc (9998) is the raw at-trade swing, but the
    // asset he actually received got flipped away for a bust (realized ktc
    // 200) — the visible Value column on the ledger is flip-aware, so a
    // "worth Nx" or "Sweep" claim built off raw received_ktc would contradict
    // it. A second, unflipped asset keeps the "alone outscored"/playoff
    // findings alive so the component still renders, isolating the fix.
    const winner = makeSide({
      user_id: "u1", owner_name: "Mikey", received_ktc: 9998, production_started: 715,
      breakdown: [
        mkAsset("Big Stud", 700, 700, 100, 500),
        mkFlipped("Flipped Pick", /* becameKtc */ 200, /* started */ 15, /* total */ 20, /* playoff */ 0),
      ],
    });
    // Tom's realized value (3000, unflipped) is actually HIGHER than Mikey's
    // realized value (500 + 200 = 700), the opposite of the raw received_ktc
    // comparison (9998 vs 1000).
    const loser = makeSide({
      user_id: "u2", owner_name: "Tom", received_ktc: 1000, production_started: 50,
      breakdown: [mkAsset("Solid RB", 50, 60, 10, 3000)],
    });
    render(<TradeFindings sides={[winner, loser]} winner_user_id="u1" />);
    expect(screen.getByText("Findings")).toBeTruthy();
    // still fires: Big Stud (700 started) alone > Tom's whole return (50)
    expect(screen.getByText(/alone outscored Tom's entire return/i)).toBeTruthy();
    // no "×" value-multiple claim: realized 700 vs 3000 doesn't clear the bar
    // (the raw received_ktc ratio, 9998 vs 1000 = 9.998x, would have)
    expect(screen.queryByText(/×/)).toBeNull();
    // no "Sweep" claim: Mikey's realized ktc (700) is actually LOWER than
    // Tom's (3000), so he did not win every column
    expect(screen.queryByText("Sweep")).toBeNull();
  });

  it("surfaces drop regret when a dropped player balled afterward", () => {
    const dropped = {
      label: "Geno Smith", kind: "player" as const, player_id: "g",
      ktc: 0, production_total: 0, production_regular: 0, production_playoff: 0,
      production_toilet: 0, production_started: 0, production_after_drop: 180,
      terminal_state: "dropped" as const,
    };
    const winner = makeSide({ user_id: "u1", owner_name: "Mikey", received_ktc: 9000, production_started: 700 });
    const loser = makeSide({ user_id: "u2", owner_name: "Tom", received_ktc: 1000, production_started: 100, breakdown: [dropped] });
    render(<TradeFindings sides={[winner, loser]} winner_user_id="u1" />);
    expect(screen.getByText(/dropped Geno Smith, who put up 180 over the next 10 weeks/i)).toBeTruthy();
  });
});
