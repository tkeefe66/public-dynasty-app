import { describe, it, expect } from "vitest";
import { ratingDrivers, ownerIdentitySlot } from "../../components/ownerdeepdive/util";
import { FranchiseRating } from "../../lib/types";

function fr(signals: Record<string, number>): FranchiseRating {
  const sig = Object.fromEntries(
    Object.entries(signals).map(([k, contribution]) => [k, { raw: 0, z: 0, weight: 0.1, contribution }]),
  );
  return {
    letter: "B", rating: 1550, rank: 3, of: 12, trend: 0,
    pillars: { results: { weight: 0.5, z: 0, contribution: 10, signals: sig } },
  };
}

describe("ratingDrivers", () => {
  it("picks the most positive signal as driver and most negative as drag, using display labels", () => {
    const r = ratingDrivers(fr({ championships: 42, lineup_skill: -31, youth: 5 }));
    expect(r).toEqual({ driver: "Championships", drag: "Lineup Skill" });
  });

  it("returns null halves when no signal crosses the ±1 point threshold on that side", () => {
    expect(ratingDrivers(fr({ championships: 42, youth: 0.5 }))).toEqual({ driver: "Championships", drag: null });
    expect(ratingDrivers(fr({ lineup_skill: -31, youth: -0.5 }))).toEqual({ driver: null, drag: "Lineup Skill" });
  });

  it("returns both null for an empty breakdown", () => {
    expect(ratingDrivers(fr({}))).toEqual({ driver: null, drag: null });
  });

  it("falls back to the raw signal key when unmapped", () => {
    expect(ratingDrivers(fr({ mystery_signal: 9 })).driver).toBe("mystery_signal");
  });
});

describe("ownerIdentitySlot", () => {
  it("is deterministic — same user_id always returns the same slot", () => {
    const uid = "123456789012345678";
    expect(ownerIdentitySlot(uid)).toBe(ownerIdentitySlot(uid));
  });

  it("always returns a value in 1-6", () => {
    const ids = ["a", "b", "c", "owner-1", "owner-2", "999999999999999999", "", "sleeper-user-abcxyz"];
    for (const id of ids) {
      const slot = ownerIdentitySlot(id);
      expect(slot).toBeGreaterThanOrEqual(1);
      expect(slot).toBeLessThanOrEqual(6);
    }
  });

  it("does not depend on array order — computed purely from the id string", () => {
    const uids = ["111", "222", "333", "444"];
    const slots = uids.map(ownerIdentitySlot);
    const reversedSlots = [...uids].reverse().map(ownerIdentitySlot).reverse();
    expect(reversedSlots).toEqual(slots);
  });

  it("spreads distinct ids across multiple slots (not a constant function)", () => {
    const uids = Array.from({ length: 30 }, (_, i) => `sleeper-owner-${i}`);
    const slots = new Set(uids.map(ownerIdentitySlot));
    expect(slots.size).toBeGreaterThan(1);
  });
});
