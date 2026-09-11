import { describe, it, expect } from "vitest";
import {
  verdict, winnerLine, robbedLine, gradeVerdict,
  winName, lossName, areRivals, archetypeOf, roastOf, Matchup,
} from "../lib/swagger";
import { ProfilesMap } from "../lib/types";

const NONE: ProfilesMap = {};

function matchup(over: Partial<Matchup> = {}): Matchup {
  return {
    winnerUid: "u_tom", winnerName: "Taylor",
    loserUid: "u_mike", loserName: "Morgan",
    lens: "ktc", profiles: NONE, ...over,
  };
}

describe("swagger voice", () => {
  it("builds a verdict with the lens-appropriate verb and grouped number", () => {
    expect(verdict(matchup(), "+2755")).toBe(
      "Taylor fleeced Morgan for 2,755 in trade value.",
    );
    expect(verdict(matchup({ lens: "production" }), "+406.8")).toBe(
      "Taylor out-scored Morgan for 406.8 in points.",
    );
  });

  it("phrases the heist and the robbery name lines", () => {
    expect(winnerLine(matchup())).toBe("Taylor fleeced Morgan");
    // Got-Robbed card: winner slot is the robber, loser slot got beat.
    expect(robbedLine(matchup({ winnerUid: "u_tom", winnerName: "Taylor", loserUid: "u_mike", loserName: "Morgan" })))
      .toBe("Morgan handed it to Taylor");
  });

  it("maps letter grades to a one-word read", () => {
    expect(gradeVerdict("A−")).toBe("Robber baron");
    expect(gradeVerdict("D")).toBe("League charity");
    expect(gradeVerdict("")).toBe("");
  });
});

describe("profile-aware names", () => {
  const profiles: ProfilesMap = {
    u_mike: { win_name: "Morgan", loss_name: "Finley", roast: "always checking the waiver wire", archetype: "The Planner" },
    u_joey: { win_name: "Drew", loss_name: "Ellis", rivals: ["u_tom"] },
  };

  it("uses win_name for the winner and loss_name for the loser", () => {
    const m = matchup({
      winnerUid: "u_mike", winnerName: "MorganAPI",
      loserUid: "u_joey", loserName: "DrewAPI",
      profiles,
    });
    expect(verdict(m, "+1000")).toBe("Morgan fleeced Ellis for 1,000 in trade value.");
  });

  it("falls back to the API display name when no profile name is set", () => {
    expect(winName("u_ghost", "Casper", profiles)).toBe("Casper");
    expect(lossName(undefined, "Anon", profiles)).toBe("Anon");
  });

  it("detects a rivalry from either side and spices the verdict", () => {
    expect(areRivals("u_tom", "u_joey", profiles)).toBe(true); // first owner lists the second as a rival
    expect(areRivals("u_joey", "u_tom", profiles)).toBe(true); // symmetric
    expect(areRivals("u_tom", "u_mike", profiles)).toBe(false);
    const m = matchup({
      winnerUid: "u_joey", winnerName: "Drew",
      loserUid: "u_tom", loserName: "Taylor", profiles,
    });
    expect(verdict(m, "+500")).toBe("Drew fleeced his rival Taylor for 500 in trade value.");
    expect(winnerLine(m)).toBe("Drew fleeced rival Taylor");
  });

  it("exposes archetype and roast with empty-string fallbacks", () => {
    expect(archetypeOf("u_mike", profiles)).toBe("The Planner");
    expect(roastOf("u_mike", profiles)).toBe("always checking the waiver wire");
    expect(roastOf("u_joey", profiles)).toBe("");
    expect(archetypeOf(undefined, profiles)).toBe("");
  });
});
