import { describe, it, expect } from "vitest";
import { leagueRedirectTarget } from "@/lib/league-config";

describe("leagueRedirectTarget", () => {
  it("returns the dashboard path when a league id is set", () => {
    expect(leagueRedirectTarget("9000000000000000001")).toBe("/league/9000000000000000001");
  });
  it("trims surrounding whitespace", () => {
    expect(leagueRedirectTarget("  123 ")).toBe("/league/123");
  });
  it("returns null when unset or blank", () => {
    expect(leagueRedirectTarget(undefined)).toBeNull();
    expect(leagueRedirectTarget("")).toBeNull();
    expect(leagueRedirectTarget("   ")).toBeNull();
  });
});
