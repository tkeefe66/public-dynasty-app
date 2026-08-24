import { describe, it, expect } from "vitest";
import { franchiseLetterTone } from "../components/ownerdeepdive/util";
import { leaderboardCard } from "../lib/og-card-data";
import type { LeaderboardResp } from "../lib/types";
import { gmRow } from "./helpers";

/**
 * The ramp runs on the `-strong` pair, and this is the token's OWN case:
 * `.design/tokens/colors.css` introduces `--pos-strong`/`--neg-strong` as
 * "Large tone-ramped glyphs ONLY (the franchise grade letter)". The ramp used
 * the base pair everywhere, which is exactly backwards — and it measured:
 * a D letter at `text-neg/70` came to **2.86:1 on `--bg`**, missing even the
 * 3:1 large-text floor. On `-strong/70` it is 4.10:1. An A went from 2.90:1 to
 * 4.94:1.
 */
describe("franchiseLetterTone", () => {
  it("ramps A→F, with F more severe than D", () => {
    expect(franchiseLetterTone("A+")).toBe("text-pos-strong");
    expect(franchiseLetterTone("B")).toBe("text-ink");
    expect(franchiseLetterTone("C")).toBe("text-ink/70");
    expect(franchiseLetterTone("D")).toBe("text-neg-strong/70");  // soft red
    expect(franchiseLetterTone("F")).toBe("text-neg-strong");     // full red, worst
  });

  it("keys off the head letter, ignoring +/- modifiers", () => {
    expect(franchiseLetterTone("D+")).toBe("text-neg-strong/70");
    expect(franchiseLetterTone("A-")).toBe("text-pos-strong");
  });
});

describe("leaderboardCard", () => {
  it("carries the Franchise letter for each standings row", () => {
    const resp: LeaderboardResp = {
      league_id: "L", scope: "all", generated_at: "2026-01-01T00:00:00Z",
      rows: [
        gmRow({ user_id: "alice", rank: 1, rating: 1840, letter: "A+" }),
        gmRow({ user_id: "carol", rank: 2, rating: 1180, letter: "D" }),
      ],
    };
    const card = leaderboardCard(resp, "Bros");
    expect(card.rows.map((s) => s.letter)).toEqual(["A+", "D"]);
  });
});
