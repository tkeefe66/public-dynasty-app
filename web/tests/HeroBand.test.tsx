import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HeroBand } from "../components/ownerdeepdive/HeroBand";
import { OwnerDetailResp } from "../lib/types";
import { pillar } from "./helpers";

/** A detail payload carrying a franchise rating + roster rank, the two
 *  ingredients the hero's receipt line reads. `rosterRank` doubles as both
 *  the roster-strength rank and the franchise-rating rank so one fixture
 *  covers both — tests that care about one independent of the other pass
 *  an override. */
function detailWithRating(
  letter: string,
  rating: number,
  rosterRank: number | null,
  of: number,
): OwnerDetailResp {
  return {
    league_id: "L",
    user_id: "u_a",
    owner: { user_id: "u_a", owner_name: "tom" },
    totals_by_lens: { ktc: 0, production: 0, regular: 0, playoff: 0, toilet: 0 },
    career_arc: [],
    trades: [],
    best_trade_id: null,
    worst_trade_id: null,
    roster_rank: rosterRank === null ? null : { rank: rosterRank, of },
    franchise_rating: {
      letter,
      rating,
      rank: rosterRank ?? 1,
      of,
      trend: 12,
      pillars: { results: pillar(50), assets: pillar(-30) },
    },
    track_record: {
      seasons: [],
      titles: 0,
      runner_ups: 0,
      playoff_appearances: 0,
      seasons_played: 3,
      best_finish: 9,
      career_wins: 16,
      career_losses: 26,
      career_ties: 0,
    },
  };
}

describe("HeroBand — the letter stands alone", () => {
  it("renders the letter with nothing under it", () => {
    render(<HeroBand detail={detailWithRating("B-", 1487, 6, 12)} rivalNames={[]} />);
    expect(screen.getByText("B-")).toBeTruthy();
    expect(screen.queryByText(/ROSTER #/i)).toBeNull();
    expect(screen.queryByText(/1,?487/)).toBeNull();
    expect(screen.queryByText(/drag:/i)).toBeNull();
  });

  it("keeps the rank on the letter's aria-label — a screen reader has no other route to it", () => {
    render(<HeroBand detail={detailWithRating("B-", 1487, 6, 12)} rivalNames={[]} />);
    expect(screen.getByLabelText(/Grade B-, ranked 6 of 12 rated/i)).toBeTruthy();
  });

  it("renders the franchise blurb below the rings strip", () => {
    const detail = {
      ...detailWithRating("C", 1500, 6, 12),
      franchise_blurb: "Despite a descending window...",
    };
    render(<HeroBand detail={detail} rivalNames={[]} />);
    expect(screen.getByText(/descending window/i)).toBeTruthy();
  });

  it("renders nothing in the blurb's place when the API sends none", () => {
    render(<HeroBand detail={detailWithRating("C", 1500, 6, 12)} rivalNames={[]} />);
    expect(screen.queryByText(/descending window/i)).toBeNull();
  });

  it("keeps the rings strip", () => {
    render(<HeroBand detail={detailWithRating("C", 1500, 6, 12)} rivalNames={[]} />);
    expect(screen.getByText(/Playoff trips/i)).toBeTruthy();
  });
});

describe("HeroBand — an unrated franchise", () => {
  function unrated(reason: "first_season" | "new_franchise"): OwnerDetailResp {
    const d = detailWithRating("C", 1500, 4, 12);
    return { ...d, franchise_rating: null, unrated_reason: reason };
  }

  it("captions a replacement manager 'new franchise' instead of a letter", () => {
    render(<HeroBand detail={unrated("new_franchise")} rivalNames={[]} />);
    expect(screen.getByText("new franchise")).toBeTruthy();
    expect(screen.queryByText("C")).toBeNull();
  });

  it("captions a league that has played nothing 'first season'", () => {
    render(<HeroBand detail={unrated("first_season")} rivalNames={[]} />);
    expect(screen.getByText("first season")).toBeTruthy();
  });

  it("keeps the roster rank — a census fact, not a verdict", () => {
    render(<HeroBand detail={unrated("new_franchise")} rivalNames={[]} />);
    expect(screen.getByText(/ROSTER #4 OF 12/i)).toBeTruthy();
  });

  it("renders no rail at all when the rating is merely missing", () => {
    const d = detailWithRating("C", 1500, 4, 12);
    render(<HeroBand detail={{ ...d, franchise_rating: null }} rivalNames={[]} />);
    expect(screen.queryByText("first season")).toBeNull();
    expect(screen.queryByText("new franchise")).toBeNull();
  });
});

describe("HeroBand — the read panel", () => {
  const SEGMENTS = [
    { text: "73%", mark: "num" },
    { text: " of value sits with ", mark: null },
    { text: "Jahmyr Gibbs", mark: "who" },
    { text: " — ", mark: null },
    { text: "contention now", mark: "good" },
    { text: ", but ", mark: null },
    { text: "QB depth", mark: "risk" },
    { text: " is thin.", mark: null },
  ];

  function withRead(over: Partial<OwnerDetailResp> = {}): OwnerDetailResp {
    return {
      ...detailWithRating("A", 1700, 1, 12),
      franchise_blurb: "73% of value sits with Jahmyr Gibbs — contention now, but QB depth is thin.",
      franchise_lead: "The league's top roster, and its youngest.",
      franchise_segments: SEGMENTS,
      ...over,
    };
  }

  it("sets the lead above the body, with no label above it", () => {
    render(<HeroBand detail={withRead()} rivalNames={[]} />);
    // No mono kicker: the lead IS the heading. Pinned because the panel
    // carried a "The read" label until it read as chrome on the page.
    expect(screen.queryByText(/^the read$/i)).toBeNull();
    const lead = screen.getByText(/top roster, and its youngest/i);
    expect(lead.className).toContain("text-lead");
    expect(lead.className).toContain("font-display");
  });

  it("gives each segment its mark's treatment", () => {
    render(<HeroBand detail={withRead()} rivalNames={[]} />);
    expect(screen.getByText("73%").className).toContain("font-mono");
    expect(screen.getByText("Jahmyr Gibbs").className).toContain("font-semibold");
    expect(screen.getByText("contention now").className).toContain("text-pos-strong");
    expect(screen.getByText("QB depth").className).toContain("text-neg-strong");
  });

  it("carries the loose leading the figure hairline needs", () => {
    const { container } = render(<HeroBand detail={withRead()} rivalNames={[]} />);
    // 1px under the baseline crowds descenders at a snug leading, so the body
    // sets looser than prose does elsewhere. Not a stray value.
    expect(container.querySelector(".leading-\\[1\\.72\\]")).toBeTruthy();
  });

  it("renders an unknown mark as plain prose, never as a fifth treatment", () => {
    const detail = withRead({
      franchise_segments: [{ text: "loud", mark: "shout" }, { text: " core.", mark: null }],
    });
    render(<HeroBand detail={detail} rivalNames={[]} />);
    const el = screen.getByText("loud");
    expect(el.className).not.toMatch(/text-(pos|neg|stamp)/);
    expect(el.className).not.toContain("font-mono");
  });

  it("falls back to plain text when a cached blurb has no segments", () => {
    const detail = withRead({ franchise_lead: null, franchise_segments: null });
    render(<HeroBand detail={detail} rivalNames={[]} />);
    // The panel still stands — an older blurb is prose, not an empty panel
    // and not a missing section.
    expect(screen.getByText(/QB depth is thin/i)).toBeTruthy();
    expect(screen.queryByText("QB depth")).toBeNull();
  });

  it("renders no panel at all when there is no blurb", () => {
    render(<HeroBand detail={detailWithRating("A", 1700, 1, 12)} rivalNames={[]} />);
    expect(screen.queryByText(/top roster, and its youngest/i)).toBeNull();
  });

  it("renders the lead alone if the body is somehow empty", () => {
    const detail = withRead({ franchise_blurb: null, franchise_segments: null });
    render(<HeroBand detail={detail} rivalNames={[]} />);
    expect(screen.getByText(/top roster, and its youngest/i)).toBeTruthy();
  });
});
