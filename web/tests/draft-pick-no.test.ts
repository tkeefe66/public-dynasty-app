import { describe, expect, it } from "vitest";
import { pickPositionInRound } from "@/lib/draft-pick-no";

describe("pickPositionInRound", () => {
  it("round 1: slot and within-round position coincide", () => {
    // A broken implementation that just returns `slot` still passes this
    // one — it's the round-2 case below that actually bites.
    expect(pickPositionInRound(12, 1, 12, 12)).toBe(12);
    expect(pickPositionInRound(1, 1, 1, 12)).toBe(1);
  });

  it("round 2 of a snake draft: diverges from slot, and ascends", () => {
    // Real 2025-class data: a 12-team snake draft, round 2 runs in reverse
    // slot order (12, 11, 10, ...) but must still label 2.01, 2.02, 2.03 —
    // ascending, because "2.01" universally means round 2's first pick.
    expect(pickPositionInRound(13, 2, 12, 12)).toBe(1);
    expect(pickPositionInRound(14, 2, 11, 12)).toBe(2);
    expect(pickPositionInRound(15, 2, 10, 12)).toBe(3);
  });

  it("falls back to slot when picks_in_round is missing or zero", () => {
    expect(pickPositionInRound(14, 2, 11, undefined)).toBe(11);
    expect(pickPositionInRound(14, 2, 11, 0)).toBe(11);
    expect(pickPositionInRound(14, 2, 11, null)).toBe(11);
  });

  it("falls back to slot rather than a non-positive position on bad data", () => {
    // pick_no inconsistent with round/picks_in_round would otherwise divide
    // out to <= 0 — never render a negative or zero pick position.
    expect(pickPositionInRound(1, 3, 5, 12)).toBe(5);
  });
});
