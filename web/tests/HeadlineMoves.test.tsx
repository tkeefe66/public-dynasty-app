import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { HeadlineMoves } from "../components/HeadlineMoves";
import { DashboardResp, LatestTrade } from "@/lib/types";

function trade(over: Partial<LatestTrade> = {}): LatestTrade {
  return {
    trade_id: "tx1",
    date: "2024-10-01",
    week: 4,
    parties: [
      { user_id: "u_tom", owner_name: "Tom" },
      { user_id: "u_mike", owner_name: "Mike" },
    ],
    assets_short: "Bijan ↔ 2025 1st",
    swing_ktc: 1450,
    swing_prod: 120.5,
    value_winner: { user_id: "u_tom", owner_name: "Tom" },
    production_winner: { user_id: "u_tom", owner_name: "Tom" },
    production_split: [140.0, 19.5] as [number, number],
    ...over,
  };
}

function owner(name: string) {
  return { user_id: `u_${name.toLowerCase()}`, owner_name: name };
}

function data(over: Partial<DashboardResp> = {}): DashboardResp {
  return {
    selected_year: "all",
    selected_lens: "ktc",
    headline_trades: [trade()],
    hero_stats: { biggest_weekly_rise: { value: "—", context: "" } },
    ...over,
  } as unknown as DashboardResp;
}

describe("HeadlineMoves — offseason (default) phase: trade of the week", () => {
  it("links the headline to the trade's detail page", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getByRole("link", { name: /Read the trade/ }))
      .toHaveAttribute("href", "/league/L1/trade/tx1");
  });

  it("renders the exit link as a bordered pill CTA, not a bare text link", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    const exit = screen.getByRole("link", { name: /Read the trade/ });
    expect(exit.className).toMatch(/rounded-pill/);
    expect(exit.className).toMatch(/border-ink/);
  });

  it("shows the kicker, phase note, and real swing figures — never invented", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getByText("Trade of the week")).toBeInTheDocument();
    expect(screen.getByText("Offseason")).toBeInTheDocument();
    // The figure block's Value/Points rows reconcile with the trade's own
    // swing_ktc/production_split — the same numbers named in the body sentence.
    expect(screen.getAllByText("+1,450").length).toBeGreaterThan(0);
    expect(screen.getByTestId("lead-points").textContent).toBe("140.0 vs 19.5");
  });

  it("gives the figures the rail — no subject column repeating the headline", () => {
    // The trade lead names the players in the body and the owners in the
    // headline; a third copy in a 250px rail truncated all three columns
    // ("David Mo… +12,483"). The figure block is label + figure only.
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getByText("Value").parentElement!.childElementCount).toBe(3);
  });

  it("shows an honest empty state when there are no trades, with a real link out", () => {
    render(<HeadlineMoves data={data({ headline_trades: [] })} leagueId="L1" />);
    expect(screen.getByText(/No trades yet/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Browse trades/ }),
    ).toHaveAttribute("href", "/league/L1?tab=trades&year=all&lens=ktc");
  });
});

describe("HeadlineMoves — regular-season phase", () => {
  it.each([
    { highId: "same-owner", tradedId: "same-owner", highName: "Alice", tradedName: "Updated name", combined: true },
    { highId: "first-owner", tradedId: "second-owner", highName: "Alex", tradedName: "Alex", combined: false },
  ])("connects trade points to the high score by identity: $combined", ({ highId, tradedId, highName, tradedName, combined }) => {
    // Mutation: join the two leaders by display name instead of source user ID.
    render(<HeadlineMoves leagueId="L1" data={data({
      phase: "regular", phase_week: 5,
      week_recap: {
        season: "2026", week: 4,
        high_score: { user_id: highId, owner: owner(highName), points: 189.2 },
        blowout: { winner_user_id: "third-owner", winner: owner("Charlie"), loser_user_id: "fourth-owner", loser: owner("Dana"), margin: 55.1 },
        traded_points: { user_id: tradedId, owner: owner(tradedName), points: 95.3 },
      },
    })} />);
    if (combined) {
      expect(screen.getByText(/of those points, the most in the league/)).toHaveTextContent("95.3");
      expect(screen.queryByText(/led the trade returns/)).not.toBeInTheDocument();
    } else {
      expect(screen.getByText(/Alex led the trade returns/)).toHaveTextContent("95.3");
      expect(screen.queryByText(/of those points/)).not.toBeInTheDocument();
    }
  });

  it("keeps a visible placeholder when no recap has landed yet", () => {
    // No week_recap: the week isn't final (or the cache predates the field).
    render(<HeadlineMoves data={data({ phase: "regular", phase_week: 4 })} leagueId="L1" />);
    expect(screen.getByText("Week 4 recap")).toBeInTheDocument();
    expect(screen.getByText("Awaiting final scores")).toBeInTheDocument();
    expect(screen.getByText(/once the week is final/)).toBeInTheDocument();
    expect(screen.queryByText(/set the bar/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse The Analyst" }))
      .toHaveAttribute("href", "/league/L1/analyst");
  });

  it("prints the recap figures once the week is final", () => {
    // Mutation: describe Bob's traded-player points as part of Alice's score/margin.
    render(
      <HeadlineMoves
        data={data({
          phase: "regular",
          phase_week: 5,
          week_recap: {
            season: "2026",
            week: 4,
            high_score: { user_id: "u_a", owner: owner("Alice"), points: 140 },
            blowout: {
              winner_user_id: "u_a", winner: owner("Alice"),
              loser_user_id: "u_b", loser: owner("Bob"),
              margin: 50,
            },
            traded_points: { user_id: "u_b", owner: owner("Bob"), points: 21.5 },
          },
        })}
        leagueId="L1"
      />,
    );
    // The recap week is the completed week (4), not the current week (5).
    expect(screen.getByText("Week 4 recap")).toBeInTheDocument();
    expect(screen.getByText("Alice set the bar.")).toBeInTheDocument();
    expect(screen.getByLabelText("Biggest margin: Alice beat Bob by 50.0 points")).toBeInTheDocument();
    expect(screen.getByText(/Bob led the trade returns:/))
      .toBeInTheDocument();
    // Preserve the score, winning margin, and a different owner's trade points
    // as distinct figures in the story.
    expect(screen.getAllByText("140.0").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+50.0").length).toBeGreaterThan(0);
    expect(screen.getAllByText("21.5").length).toBeGreaterThan(0);
  });

  it("does not infer that nobody started a traded player from an absent tally", () => {
    // Mutation: turn an absent tally into the categorical claim that nobody scored.
    render(
      <HeadlineMoves
        data={data({
          phase: "regular",
          phase_week: 5,
          week_recap: {
            season: "2026",
            week: 4,
            high_score: { user_id: "u_a", owner: owner("Alice"), points: 99.25 },
            blowout: {
              winner_user_id: "u_a", winner: owner("Alice"),
              loser_user_id: "u_b", loser: owner("Bob"),
              margin: 3.5,
            },
            traded_points: null,
          },
        })}
        leagueId="L1"
      />,
    );
    expect(screen.queryByText(/Nobody started a trade-acquired player for points/))
      .not.toBeInTheDocument();
    expect(screen.getByLabelText("Biggest margin: Alice beat Bob by 3.5 points")).toBeInTheDocument();
  });
});

describe("HeadlineMoves — postseason phase", () => {
  const watch = (over = {}) => ({
    season: 2025,
    entered: 6,
    alive_count: 4,
    alive: [owner("Tom"), owner("Mike"), owner("Ann"), owner("Joe")],
    top_seed_owner: owner("Ann"),
    top_seed: 1,
    playoff_points_leader: owner("Mike"),
    playoff_points: 284.6,
    ...over,
  });

  const post = (over = {}) =>
    data({ phase: "post", phase_week: 16, bracket_watch: watch(over) });

  it("counts the field still alive", () => {
    render(<HeadlineMoves data={post()} leagueId="L1" />);
    expect(screen.getByText("Bracket watch")).toBeInTheDocument();
    expect(screen.getByText("Wk 16")).toBeInTheDocument();
    expect(screen.getByText("4 teams are still alive.")).toBeInTheDocument();
    expect(screen.getByText("4 / 6")).toBeInTheDocument();
  });

  it("names both finalists once the field is down to two", () => {
    render(
      <HeadlineMoves
        data={post({ alive_count: 2, alive: [owner("Tom"), owner("Mike")] })}
        leagueId="L1"
      />,
    );
    expect(screen.getByText("Tom and Mike are playing for it.")).toBeInTheDocument();
  });

  it("crowns the last team standing", () => {
    render(
      <HeadlineMoves
        data={post({ alive_count: 1, alive: [owner("Tom")] })}
        leagueId="L1"
      />,
    );
    expect(screen.getByText("Tom is your champion.")).toBeInTheDocument();
  });

  it("labels the strip alive / top seed / playoff pts", () => {
    render(<HeadlineMoves data={post()} leagueId="L1" />);
    expect(screen.getByText("Alive")).toBeInTheDocument();
    expect(screen.getByText("Top seed")).toBeInTheDocument();
    expect(screen.getByText("Playoff pts")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("284.6")).toBeInTheDocument();
  });

  it("prints the em-dash rather than guessing an unknown seed", () => {
    render(
      <HeadlineMoves
        data={post({ top_seed_owner: null, top_seed: null })}
        leagueId="L1"
      />,
    );
    expect(screen.getByText("Top seed")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("says nobody has scored yet rather than naming a zero leader", () => {
    render(
      <HeadlineMoves
        data={post({ playoff_points_leader: null, playoff_points: null })}
        leagueId="L1"
      />,
    );
    expect(
      screen.getByText(/No owner has scored playoff points from a trade-acquired player yet/),
    ).toBeInTheDocument();
  });

  it("shows a real placeholder before the bracket is posted", () => {
    render(<HeadlineMoves data={data({ phase: "post", phase_week: 15 })} leagueId="L1" />);
    expect(screen.getByText("Bracket watch")).toBeInTheDocument();
    expect(screen.getByText("Wk 15")).toBeInTheDocument();
    expect(screen.getByText(/hasn't been posted yet/)).toBeInTheDocument();
  });
});

describe("HeadlineMoves — draft phase", () => {
  const review = {
    season: 2025,
    graded: true,
    best: {
      player_id: "p1", full_name: "Jaxon Smith-Njigba", position: "WR",
      drafter_id: "u_mike", owner: owner("Mike"),
      round: 3, slot: 4, draft_position: 28, production_total: 910.4,
      slot_delta: 27, baseline_delta: null, baseline_source: "",
    },
    worst: {
      player_id: "p2", full_name: "Bijan Robinson", position: "RB",
      drafter_id: "u_tom", owner: owner("Tom"),
      round: 1, slot: 2, draft_position: 2, production_total: 44.0,
      slot_delta: -19, baseline_delta: null, baseline_source: "",
    },
    beat_slot: 11,
    total: 36,
    best_value: null,
    reach: null,
    matched: 0,
  };

  it("leads with the pick that most outproduced its slot", () => {
    render(<HeadlineMoves data={data({ phase: "draft", draft_review: review })} leagueId="L1" />);
    expect(screen.getByText("Draft review")).toBeInTheDocument();
    // No top-right phase note on the draft card — the kicker already says
    // "Draft review".
    expect(screen.queryByText("Draft window")).not.toBeInTheDocument();
    expect(
      screen.getByText("Mike got the best pick of the 2025 draft at 3.04."),
    ).toBeInTheDocument();
  });

  it("labels the strip best / worst / beat slot", () => {
    render(<HeadlineMoves data={data({ phase: "draft", draft_review: review })} leagueId="L1" />);
    expect(screen.getByText("Best pick")).toBeInTheDocument();
    expect(screen.getByText("Worst pick")).toBeInTheDocument();
    expect(screen.getByText("Beat slot")).toBeInTheDocument();
    expect(screen.getByText("11 / 36")).toBeInTheDocument();
  });

  it("zero-pads the slot so picks sort and align as 3.04, not 3.4", () => {
    render(<HeadlineMoves data={data({ phase: "draft", draft_review: review })} leagueId="L1" />);
    expect(screen.getByText("3.04")).toBeInTheDocument();
    expect(screen.getByText("1.02")).toBeInTheDocument();
  });

  it("falls back to trade-of-the-week when the class hasn't played yet", () => {
    // No review is the honest state right after a draft: every pick sits at
    // 0.0, so naming a "best" one would invent it out of ties.
    render(<HeadlineMoves data={data({ phase: "draft" })} leagueId="L1" />);
    expect(screen.getByText("Trade of the week")).toBeInTheDocument();
    expect(screen.queryByText("Draft window")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Read the trade/ })).toBeInTheDocument();
  });

  const ungradedReview = {
    season: 2026,
    graded: false,
    best: null,
    worst: null,
    beat_slot: 0,
    total: 36,
    best_value: {
      player_id: "p3", full_name: "Faller Guy", position: "WR",
      drafter_id: "u_carol", owner: owner("Carol"),
      round: 2, slot: 5, draft_position: 17, production_total: null,
      slot_delta: null, baseline_delta: 6, baseline_source: "rookie_ecr",
    },
    reach: {
      player_id: "p4", full_name: "Reach Guy", position: "RB",
      drafter_id: "u_dave", owner: owner("Dave"),
      round: 1, slot: 3, draft_position: 3, production_total: null,
      slot_delta: null, baseline_delta: -8, baseline_source: "rookie_ecr",
    },
    matched: 28,
  };

  it("leads with the steal vs consensus while the class is ungraded", () => {
    render(
      <HeadlineMoves data={data({ phase: "draft", draft_review: ungradedReview })} leagueId="L1" />,
    );
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Carol landed the steal of the 2026 draft — Faller Guy fell 6 picks past his ECR rank.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Dave reached hardest, taking Reach Guy at 1\.03/)).toBeInTheDocument();
  });

  it("labels the strip best value / biggest reach / picks while ungraded", () => {
    render(
      <HeadlineMoves data={data({ phase: "draft", draft_review: ungradedReview })} leagueId="L1" />,
    );
    expect(screen.getByText("Best value")).toBeInTheDocument();
    expect(screen.getByText("Biggest reach")).toBeInTheDocument();
    expect(screen.getByText("Picks")).toBeInTheDocument();
    // Coverage ("28 matched") was pointless once it's near-always 100% for a
    // rookie draft — the third cell grounds the class size instead.
    expect(screen.queryByText("Matched")).not.toBeInTheDocument();
    expect(screen.getByText("36")).toBeInTheDocument();
    expect(screen.getByText("+6")).toBeInTheDocument();
    expect(screen.getByText("-8")).toBeInTheDocument();
  });

  it("falls back to the generic message when nothing matched a baseline", () => {
    render(
      <HeadlineMoves
        data={data({
          phase: "draft",
          draft_review: { ...ungradedReview, best_value: null, reach: null, matched: 0 },
        })}
        leagueId="L1"
      />,
    );
    expect(screen.getByText("The 2026 draft is in the books — 36 picks.")).toBeInTheDocument();
    expect(screen.getByText(/Grading starts once the season's played a week/)).toBeInTheDocument();
  });
});

describe("HeadlineMoves — the figure strip", () => {
  it("renders exactly three cells, once — no desktop/mobile duplication", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getAllByText("Value")).toHaveLength(1);
    expect(screen.getAllByText("Points")).toHaveLength(1);
    expect(screen.getAllByText("Since")).toHaveLength(1);
  });

  it("names the winner in the headline instead of both parties", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getByText("Tom won this one on both counts.")).toBeInTheDocument();
  });

  it("keeps every figure out of the body prose", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    const body = screen.getByText(/traded/i);
    expect(body.textContent).not.toMatch(/\d,\d{3}/);   // no +1,450
    expect(body.textContent).not.toMatch(/\d+\.\d/);    // no 120.5
  });

  it("colors VALUE by sign and never colors POINTS", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    const value = screen.getByText("+1,450");
    expect(value.className).toMatch(/text-pos/);
    const points = screen.getByTestId("lead-points");
    expect(points.innerHTML).not.toMatch(/text-pos|text-neg/);
  });

  it("weights the winning production figure and dims the losing one", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    const points = screen.getByTestId("lead-points");
    expect(within(points).getByText("140.0").className).toMatch(/font-semibold/);
    expect(within(points).getByText("19.5").className).toMatch(/text-dim/);
  });

  it("emphasizes neither figure when the two round to the same string", () => {
    const t = { ...trade(), production_split: [58.31, 58.34] as [number, number] };
    render(<HeadlineMoves data={data({ headline_trades: [t] })} leagueId="L1" />);
    const points = screen.getByTestId("lead-points");
    expect(points.textContent).toBe("58.3 vs 58.3");
    for (const figure of within(points).getAllByText("58.3")) {
      expect(figure.className).not.toMatch(/font-semibold|text-dim/);
    }
  });

  it("pairs each label with its figure for a screen reader", () => {
    // The strip is two sibling grids, so the label row and the value row are
    // only associated positionally — a screen reader linearizes
    // "VALUE POINTS SINCE" and then three bare figures.
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getByTestId("lead-points"))
      .toHaveAttribute("aria-label", "Points: 140.0 vs 19.5");
    expect(screen.getByLabelText("Value: +1,450")).toBeInTheDocument();
    expect(screen.getByLabelText("Since: Oct 1, 2024")).toBeInTheDocument();
  });

  it("keeps the high score readable alongside its owner", () => {
    render(
      <HeadlineMoves
        data={data({
          phase: "regular", phase_week: 5,
          week_recap: {
            season: "2026", week: 4,
            high_score: { user_id: "u_a", owner: owner("TheCommish"), points: 140 },
            blowout: {
              winner_user_id: "u_a", winner: owner("Alice"),
              loser_user_id: "u_b", loser: owner("Bob"), margin: 50,
            },
            traded_points: null,
          },
        })}
        leagueId="L1"
      />,
    );
    expect(screen.getByRole("heading", { name: "TheCommish set the bar." })).toBeInTheDocument();
    expect(screen.getByLabelText("High score: TheCommish, 140.0 points")).toBeInTheDocument();
  });

  it("shows an em dash rather than 0.0 vs 0.0 when neither side has scored", () => {
    const t = { ...trade(), production_split: [0, 0] as [number, number] };
    render(<HeadlineMoves data={data({ headline_trades: [t] })} leagueId="L1" />);
    expect(screen.getByTestId("lead-points").textContent).toBe("—");
  });

  it("opens the completed week rather than the current week", () => {
    render(
      <HeadlineMoves
        data={data({
          phase: "regular", phase_week: 5,
          week_recap: {
            season: "2026", week: 4,
            high_score: { user_id: "u_a", owner: owner("Alice"), points: 140 },
            blowout: {
              winner_user_id: "u_a", winner: owner("Alice"),
              loser_user_id: "u_b", loser: owner("Bob"), margin: 50,
            },
            traded_points: { user_id: "u_b", owner: owner("Bob"), points: 21.5 },
          },
        })}
        leagueId="L1"
      />,
    );
    expect(screen.getByRole("link", { name: "Read the Week 4 roast" }))
      .toHaveAttribute("href", "/league/L1/analyst?edition=2026-4");
  });

  it("uses the short date form in the SINCE cell — the full month name clips at 106px", () => {
    render(<HeadlineMoves data={data()} leagueId="L1" />);
    expect(screen.getByText("Oct 1, 2024")).toBeInTheDocument();
    // The body sentence a few lines up keeps the full form — only the
    // cramped strip cell needs the abbreviation.
    expect(screen.getByText(/traded October 1, 2024/)).toBeInTheDocument();
  });

  it("preserves a long owner name and its full score", () => {
    render(
      <HeadlineMoves
        data={data({
          phase: "regular", phase_week: 5,
          week_recap: {
            season: "2026", week: 4,
            high_score: { user_id: "u_a", owner: owner("TheCommish2020"), points: 140 },
            blowout: {
              winner_user_id: "u_a", winner: owner("Alice"),
              loser_user_id: "u_b", loser: owner("Bob"), margin: 50,
            },
            traded_points: null,
          },
        })}
        leagueId="L1"
      />,
    );
    expect(screen.getByRole("heading", { name: "TheCommish2020 set the bar." })).toBeInTheDocument();
    expect(screen.getByLabelText("High score: TheCommish2020, 140.0 points")).toBeInTheDocument();
  });
});
