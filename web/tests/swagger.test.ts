import { describe, it, expect } from "vitest";
import {
  verdict, winnerLine, robbedLine, gradeVerdict,
  winName, lossName, areRivals, archetypeOf, roastOf, Matchup,
} from "../lib/swagger";
import { ProfilesMap } from "../lib/types";

const NONE: ProfilesMap = {};

function matchup(over: Partial<Matchup> = {}): Matchup {
  return {
    winnerUid: "u_tom", winnerName: "Tom",
    loserUid: "u_mike", loserName: "Mike",
    lens: "ktc", profiles: NONE, ...over,
  };
}

describe("swagger voice", () => {
  it("builds a verdict with the lens-appropriate verb and grouped number", () => {
    expect(verdict(matchup(), "+2755")).toBe(
      "Tom fleeced Mike for 2,755 in trade value.",
    );
    expect(verdict(matchup({ lens: "production" }), "+406.8")).toBe(
      "Tom out-scored Mike for 406.8 in points.",
    );
  });

  it("phrases the heist and the robbery name lines", () => {
    expect(winnerLine(matchup())).toBe("Tom fleeced Mike");
    // Got-Robbed card: winner slot is the robber, loser slot got beat.
    expect(robbedLine(matchup({ winnerUid: "u_tom", winnerName: "Tom", loserUid: "u_mike", loserName: "Mike" })))
      .toBe("Mike handed it to Tom");
  });

  it("maps letter grades to a one-word read", () => {
    expect(gradeVerdict("A−")).toBe("Robber baron");
    expect(gradeVerdict("D")).toBe("League charity");
    expect(gradeVerdict("")).toBe("");
  });
});

describe("profile-aware names", () => {
  const profiles: ProfilesMap = {
    u_mike: { win_name: "Mike", loss_name: "Michael", roast: "bought, not built", archetype: "The Loaded One" },
    u_joey: { win_name: "Joey", loss_name: "Jory", rivals: ["u_tom"] },
  };

  it("uses win_name for the winner and loss_name for the loser", () => {
    const m = matchup({
      winnerUid: "u_mike", winnerName: "MikeAPI",
      loserUid: "u_joey", loserName: "JoeyAPI",
      profiles,
    });
    expect(verdict(m, "+1000")).toBe("Mike fleeced Jory for 1,000 in trade value.");
  });

  it("falls back to the API display name when no profile name is set", () => {
    expect(winName("u_ghost", "Casper", profiles)).toBe("Casper");
    expect(lossName(undefined, "Anon", profiles)).toBe("Anon");
  });

  it("detects a rivalry from either side and spices the verdict", () => {
    expect(areRivals("u_tom", "u_joey", profiles)).toBe(true); // joey lists tom
    expect(areRivals("u_joey", "u_tom", profiles)).toBe(true); // symmetric
    expect(areRivals("u_tom", "u_mike", profiles)).toBe(false);
    const m = matchup({
      winnerUid: "u_joey", winnerName: "Joey",
      loserUid: "u_tom", loserName: "Tom", profiles,
    });
    expect(verdict(m, "+500")).toBe("Joey fleeced his rival Tom for 500 in trade value.");
    expect(winnerLine(m)).toBe("Joey fleeced rival Tom");
  });

  it("exposes archetype and roast with empty-string fallbacks", () => {
    expect(archetypeOf("u_mike", profiles)).toBe("The Loaded One");
    expect(roastOf("u_mike", profiles)).toBe("bought, not built");
    expect(roastOf("u_joey", profiles)).toBe("");
    expect(archetypeOf(undefined, profiles)).toBe("");
  });
});
