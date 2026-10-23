import { expect, it } from "vitest";
import { leagueStatus } from "../lib/league-status";

it("labels queued Yahoo cooldown as automatic retry", () => {
  // Mutation: generic queued label hides that Yahoo has paused the sync.
  expect(leagueStatus({ warm: false, refresh_job: {
    id: "job", state: "queued", reason: "yahoo_rate_limited",
  } })).toBe("Yahoo cooldown · auto-retry");
});
