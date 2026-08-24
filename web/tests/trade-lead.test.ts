import { describe, it, expect } from "vitest";
import { tradeHeadline, pointsReading } from "../lib/trade-lead";
import { LatestTrade } from "../lib/types";

function trade(over: Partial<LatestTrade> = {}): LatestTrade {
  return {
    trade_id: "tx1", date: "2025-08-29", week: 2,
    parties: [
      { user_id: "u_a", owner_name: "Bobby" },
      { user_id: "u_b", owner_name: "Joey" },
    ],
    assets_short: "David Montgomery ↔ Saquon Barkley",
    swing_ktc: 12483, swing_prod: 121.5,
    value_winner: { user_id: "u_a", owner_name: "Bobby" },
    production_winner: { user_id: "u_a", owner_name: "Bobby" },
    production_split: [179.8, 58.3],
    ...over,
  };
}

describe("tradeHeadline", () => {
  it("names one winner when both lenses agree", () => {
    expect(tradeHeadline(trade())).toBe("Bobby won this one on both counts.");
  });

  it("names the tension when the lenses disagree", () => {
    const t = trade({
      production_winner: { user_id: "u_b", owner_name: "Joey" },
      production_split: [58.3, 179.8],
    });
    expect(tradeHeadline(t)).toBe("Bobby won the value. Joey won the field.");
  });

  it("falls back to both names when a winner is missing", () => {
    const t = trade({ value_winner: null, production_winner: null });
    expect(tradeHeadline(t)).toBe(
      "Bobby & Joey's trade is still the loudest swing on the board.",
    );
  });

  it("falls back when only the value winner is missing", () => {
    const t = trade({ value_winner: null });
    expect(tradeHeadline(t)).toBe(
      "Bobby & Joey's trade is still the loudest swing on the board.",
    );
  });

  it("says nobody's scored when the value is settled and the field isn't", () => {
    // The backend leaves production_winner null on a tie, which before week 1
    // of a season is every trade. Claiming a field winner there contradicts
    // the POINTS cell three lines below.
    const t = trade({ production_winner: null, production_split: [0, 0] });
    expect(tradeHeadline(t)).toBe("Bobby won the value. Nobody's scored yet.");
  });

  it("never claims a field result the POINTS cell contradicts", () => {
    // The headline and the strip read from the same payload; an unscored
    // POINTS cell and a "won the field" headline can never coexist.
    for (const production_winner of [
      null,
      { user_id: "u_a", owner_name: "Bobby" },
      { user_id: "u_b", owner_name: "Joey" },
    ]) {
      const t = trade({ production_winner, production_split: [0, 0] });
      expect(pointsReading(t)).toEqual({ kind: "unscored" });
      expect(tradeHeadline(t)).not.toMatch(/won the field|on both counts/);
    }
  });
});

describe("pointsReading", () => {
  it("reads head-to-head with the value winner on the left", () => {
    expect(pointsReading(trade())).toEqual({
      kind: "split", left: "179.8", right: "58.3", winner: "left",
    });
  });

  it("marks the right side as the winner when the lenses disagree", () => {
    const t = trade({
      production_winner: { user_id: "u_b", owner_name: "Joey" },
      production_split: [58.3, 179.8],
    });
    expect(pointsReading(t)).toEqual({
      kind: "split", left: "58.3", right: "179.8", winner: "right",
    });
  });

  it("emphasizes neither figure when the two round to the same string", () => {
    // 58.31 vs 58.34 both print "58.3". Bolding one and dimming the other
    // puts two visually identical figures at different weights.
    expect(pointsReading(trade({ production_split: [58.31, 58.34] }))).toEqual({
      kind: "split", left: "58.3", right: "58.3", winner: null,
    });
  });

  it("emphasizes neither figure on an exact tie", () => {
    expect(pointsReading(trade({ production_split: [50, 50] }))).toEqual({
      kind: "split", left: "50.0", right: "50.0", winner: null,
    });
  });

  it("is unscored when neither side has scored — never 0.0 vs 0.0", () => {
    expect(pointsReading(trade({ production_split: [0, 0] }))).toEqual({ kind: "unscored" });
  });

  it("is unscored for a trade with more than two sides — swing_prod is a spread, not a total", () => {
    expect(pointsReading(trade({ production_split: null }))).toEqual({ kind: "unscored" });
    // Even with a large spread on the payload the cell stays unscored, rather
    // than printing a figure the POINTS label would misdescribe.
    expect(pointsReading(trade({ production_split: null, swing_prod: 250.4 })))
      .toEqual({ kind: "unscored" });
  });
});
