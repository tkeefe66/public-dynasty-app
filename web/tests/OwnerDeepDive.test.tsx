import {
  describe, it, expect, beforeEach, vi,
} from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OwnerDeepDive } from "../components/OwnerDeepDive";
import { OwnerDetailResp } from "../lib/types";
import { pillar } from "./helpers";

// The Track Record tab's SideBetsCard fires a real betsSummary() on mount;
// stub it so the suite doesn't log unhandled-rejection/act() noise from an
// unmocked network call. Spread the actual module so TradesTab/ProfileEditor's
// own `@/lib/api` imports (tradesList, putProfile, ApiError, …) still work.
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    betsSummary: vi.fn().mockResolvedValue({ owners: [] }),
  };
});

const DETAIL: OwnerDetailResp = {
  league_id: "L", user_id: "u_a",
  owner: { user_id: "u_a", owner_name: "Alice", team_name: "Team A" },
  totals_by_lens: { ktc: 600, production: 70, regular: 60, playoff: 20, toilet: 5 },
  career_arc: [
    { season: 2023, net_ktc: 100, production_total: 20, production_regular: 15, production_playoff: 5, production_toilet: 2, trades: 1 },
    { season: 2024, net_ktc: 500, production_total: 50, production_regular: 45, production_playoff: 15, production_toilet: 3, trades: 1 },
  ],
  trades: [
    {
      trade_id: "t_best", date: "2024-09-12", season: 2024, week: 2,
      counterparties: [{ user_id: "u_b", owner_name: "Bob" }],
      assets_short: "Bijan Robinson", swing_ktc: 800, swing_prod: 60, swing_regular: 50, swing_playoff: 15, swing_toilet: 3,
    },
    {
      trade_id: "t_worst", date: "2023-10-01", season: 2023, week: 4,
      counterparties: [{ user_id: "u_c", owner_name: "Cara" }],
      assets_short: "2024 1st", swing_ktc: -200, swing_prod: 10, swing_regular: 5, swing_playoff: 0, swing_toilet: 0,
    },
  ],
  best_trade_id: "t_best",
  worst_trade_id: "t_worst",
  franchise_rating: {
    letter: "B+", rating: 1620, rank: 2, of: 12, trend: 1,
    pillars: { results: pillar(50), assets: pillar(40) },
    pillar_highlights: {
      results: "Two rings carry the résumé.",
      assets: "Young and pick-rich.",
    },
  },
  track_record: {
    seasons: [
      { season: 2023, rank: 3, of: 12, wins: 8, losses: 6, ties: 0, made_playoffs: true, champion: false, runner_up: true, rounds_won: 1, playoff_place: 2, made_toilet: false, toilet_place: null },
      { season: 2024, rank: 1, of: 12, wins: 11, losses: 3, ties: 0, made_playoffs: true, champion: true, runner_up: false, rounds_won: 2, playoff_place: 1, made_toilet: false, toilet_place: null },
    ],
    titles: 1, runner_ups: 1, playoff_appearances: 2, seasons_played: 2,
    best_finish: 1, career_wins: 19, career_losses: 9, career_ties: 0,
  },
  head_to_head: [
    { opponent: { user_id: "u_b", owner_name: "Bob" }, wins: 5, losses: 3, ties: 0, points_for: 900, points_against: 850 },
  ],
};

const OTHERS = [
  { user_id: "u_b", name: "Bob" },
  { user_id: "u_c", name: "Cara" },
];

/* The Outlook tab is the Assets pillar's page now — one model, no second
 * arithmetic. The fixture carries what OutlookView actually holds: the derived
 * stage plus the two pillar z's it was banded from. `strength_score`,
 * `trajectory_score` and `window_breakdown` were the retired model's own
 * fields and no producer can emit them. */
const DETAIL_WITH_OUTLOOK: OwnerDetailResp = {
  ...DETAIL,
  outlook: {
    window: "Contending",
    results_z: 0.84, assets_z: 1.12, tilt: 0.28,
    assets_signal_ranks: { roster_value_share: 3, young_core_share: 2, draft_capital: 10 },
    age_profile: { avg_age_by_position: { RB: 23.5 }, overall_avg_age: 24.2, aging_risks: [], core_young: [] },
    draft_capital: { picks_by_season: { "2027": 5 }, picks_by_season_round: {}, net_vs_average: 3, status: "pick-rich", total_value: 1800 },
    draft_needs: [],
  },
  roster_rank: { rank: 3, of: 12 },
  draft_skill: { score: 0.4, rank: 2, of: 12 },
};

describe("OwnerDeepDive", () => {
  it("leads with the Franchise Rating verdict + rings", () => {
    render(
      <OwnerDeepDive
        leagueId="L" detail={DETAIL}
        profile={{ archetype: "The Loaded One", roast: "bought, not built" }}
        others={OTHERS} onProfilesChange={() => {}}
      />,
    );
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("B+")).toBeInTheDocument();           // franchise letter
    expect(screen.getByText("The Loaded One")).toBeInTheDocument();
    expect(screen.getByText(/bought, not built/)).toBeInTheDocument();
    // Rings strip from track record — rendered once for desktop (one rule)
    // and once for mobile (two rules of two); both exist in jsdom regardless
    // of viewport, so this asserts at least one visible instance exists
    // (mirrors the established StandingsTable.test.tsx duplication pattern).
    expect(screen.getAllByText("🏆 1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("19-9").length).toBeGreaterThan(0); // career record
  });

  it("leads with the grade LETTER alone, and keeps the receipt on the page", () => {
    /* The hero rail used to stack rank, rating + trend and a carried-by line
     * under the letter — four figures competing with the one that IS the
     * verdict. "Show The Evidence, Don't Link To It" is still satisfied: the
     * evidence did not move to a second destination, it moved one line down to
     * the Overview tab's own header, which is on this same page. What must NOT
     * happen is the figures vanishing from the page entirely. */
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    // aria-label on a non-interactive <span> is not queryable by label text,
    // so assert the attribute on the element that carries the letter.
    const letter = screen.getByText("B+", { selector: "span" });
    expect(letter).toHaveAttribute("aria-label", expect.stringMatching(/ranked 2 of 12/i));
    // The rank/rating receipt still exists on the page, in the Overview
    // header — and now also in the pillar ledger's reconciling total row
    // (Base 1,500 + pillars), so this asserts at least one instance exists
    // rather than pinning down which.
    expect(screen.getAllByText(/1,620/).length).toBeGreaterThan(0);
    expect(screen.getByText(/#2 of 12/i)).toBeInTheDocument();
  });

  it("shows the Track Record tab with finishes and head-to-head", async () => {
    const user = userEvent.setup();
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    await user.click(screen.getByRole("tab", { name: /track record|record/i }));
    expect(screen.getByText("🏆 Champion")).toBeInTheDocument();
    expect(screen.getByText("🥈 Runner-up")).toBeInTheDocument();
    expect(screen.getByText("Head to head")).toBeInTheDocument();
    expect(screen.getByText("5-3")).toBeInTheDocument();          // vs Bob
  });

  it("shows the five-metric trade tiles in the Trades tab", async () => {
    const user = userEvent.setup();
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    await user.click(screen.getByRole("tab", { name: /trades/i }));
    // The five-metric strip renders a desktop and a phone variant (one visible
    // per breakpoint), so the figure appears twice in jsdom.
    expect(screen.getAllByText("+600").length).toBeGreaterThan(0);
    expect(screen.getByText(/Best heist/)).toBeInTheDocument();
    expect(screen.getByText("Every trade")).toBeInTheDocument();
    expect(screen.getByText("2 deals")).toBeInTheDocument();
    // The pan-out chart now lives here. Third-person copy: DETAIL's owner is Alice.
    expect(screen.getByText(/did alice's trades pan out/i)).toBeInTheDocument();
  });

  it("links each receipt row to the trade page", async () => {
    const user = userEvent.setup();
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    await user.click(screen.getByRole("tab", { name: /trades/i }));
    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toContain("/league/L/trade/t_best");
    expect(links).toContain("/league/L/trade/t_worst");
  });

  it("shows an empty state when there are no trades", async () => {
    const user = userEvent.setup();
    render(
      <OwnerDeepDive
        leagueId="L"
        detail={{ ...DETAIL, trades: [], best_trade_id: null, worst_trade_id: null }}
      />,
    );
    await user.click(screen.getByRole("tab", { name: /trades/i }));
    expect(screen.getByText("No trades on record")).toBeInTheDocument();
    expect(screen.queryByText(/Best heist/)).not.toBeInTheDocument();
  });

  it("omits the edit button on the read-only shared view", () => {
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    expect(screen.queryByRole("button", { name: /edit alice/i })).not.toBeInTheDocument();
  });

  it("opens the profile editor from the workspace", async () => {
    const user = userEvent.setup();
    render(
      <OwnerDeepDive
        leagueId="L" detail={DETAIL}
        others={OTHERS} onProfilesChange={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: /edit alice/i }));
    expect(screen.getByText("Edit Alice")).toBeInTheDocument();
  });

  it("explains what drives the rating on Overview", () => {
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    // The Overview leads with what validates the grade: the two v2 pillars.
    expect(screen.getByText("Why this grade")).toBeInTheDocument();
    expect(screen.getByText("Results")).toBeInTheDocument();
    expect(screen.getByText("Assets")).toBeInTheDocument();
    expect(screen.getByText("+50")).toBeInTheDocument();      // results contribution
    expect(screen.getByText(/1,620 · #2 of 12/)).toBeInTheDocument();
    // LLM per-pillar highlights render under each pillar.
    expect(screen.getByText("Two rings carry the résumé.")).toBeInTheDocument();
    expect(screen.getByText("Young and pick-rich.")).toBeInTheDocument();
    // The pan-out chart now lives in the Trades tab, not here.
    expect(screen.queryByText(/did alice's trades pan out/i)).not.toBeInTheDocument();
  });

  it("defaults to Overview and switches to Trades", async () => {
    const user = userEvent.setup();
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    expect(screen.getByRole("tab", { name: /overview/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Every trade")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /trades/i }));
    expect(screen.getByText("Every trade")).toBeInTheDocument();
  });

  describe("ARIA tabs pattern", () => {
    it("wires tabs to the panel and keeps inactive tabs out of the tab order", () => {
      render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
      const overview = screen.getByRole("tab", { name: /overview/i });
      const trades = screen.getByRole("tab", { name: /trades/i });
      const panel = screen.getByRole("tabpanel");
      // Roving tabindex: only the active tab is focusable.
      expect(overview).toHaveAttribute("tabindex", "0");
      expect(trades).toHaveAttribute("tabindex", "-1");
      // The panel is labelled by the active tab, which controls it.
      expect(panel).toHaveAttribute("aria-labelledby", overview.id);
      expect(overview).toHaveAttribute("aria-controls", panel.id);
    });

    it("moves selection and focus with Arrow / Home / End keys", async () => {
      const user = userEvent.setup();
      render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
      const overview = screen.getByRole("tab", { name: /overview/i });
      overview.focus();

      await user.keyboard("{ArrowRight}");
      const record = screen.getByRole("tab", { name: /track record|record/i });
      expect(record).toHaveAttribute("aria-selected", "true");
      expect(record).toHaveFocus();

      await user.keyboard("{End}");
      const trades = screen.getByRole("tab", { name: /trades/i });
      expect(trades).toHaveAttribute("aria-selected", "true");
      expect(trades).toHaveFocus();

      // Wraps from the last tab back to the first.
      await user.keyboard("{ArrowRight}");
      expect(overview).toHaveAttribute("aria-selected", "true");
      expect(overview).toHaveFocus();

      await user.keyboard("{ArrowLeft}");
      expect(trades).toHaveAttribute("aria-selected", "true");

      await user.keyboard("{Home}");
      expect(overview).toHaveAttribute("aria-selected", "true");
    });
  });

  describe("URL state (?tab= / ?year=)", () => {
    beforeEach(() => {
      // jsdom shares one window across tests — reset to a clean owner-page URL.
      window.history.replaceState(null, "", "/league/L/owner/u_a");
    });

    it("restores tab + trades year from deep-link params", () => {
      render(
        <OwnerDeepDive leagueId="L" detail={DETAIL} initialTab="trades" initialTradesYear={2023} syncUrl />,
      );
      expect(screen.getByRole("tab", { name: /trades/i })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("button", { name: "'23" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByText("1 deals")).toBeInTheDocument(); // 2023 has one trade
    });

    it("writes tab and year to the query string, dropping defaults", async () => {
      const user = userEvent.setup();
      render(<OwnerDeepDive leagueId="L" detail={DETAIL} syncUrl />);

      await user.click(screen.getByRole("tab", { name: /trades/i }));
      expect(window.location.search).toBe("?tab=trades");

      await user.click(screen.getByRole("button", { name: "'24" }));
      expect(window.location.search).toBe("?tab=trades&year=2024");

      // Year only makes sense on the Trades tab — leaving it drops the param…
      await user.click(screen.getByRole("tab", { name: /overview/i }));
      expect(window.location.search).toBe("");

      // …but the filter is remembered and re-serialized on return.
      await user.click(screen.getByRole("tab", { name: /trades/i }));
      expect(window.location.search).toBe("?tab=trades&year=2024");

      await user.click(screen.getByRole("button", { name: "All" }));
      expect(window.location.search).toBe("?tab=trades");
    });

    it("falls back to Overview when the deep-linked tab isn't available", () => {
      // DETAIL has no outlook, so ?tab=outlook can't render — don't strand
      // the user on an empty pane with no tab highlighted.
      render(<OwnerDeepDive leagueId="L" detail={DETAIL} initialTab="outlook" syncUrl />);
      expect(screen.getByRole("tab", { name: /overview/i })).toHaveAttribute("aria-selected", "true");
    });

    it("ignores a deep-linked year outside the owner's trade seasons", () => {
      render(
        <OwnerDeepDive leagueId="L" detail={DETAIL} initialTab="trades" initialTradesYear={1999} syncUrl />,
      );
      expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByText("2 deals")).toBeInTheDocument();
    });

    it("leaves the URL alone when syncUrl is off (dashboard Owners pane)", async () => {
      const user = userEvent.setup();
      window.history.replaceState(null, "", "/league/L?tab=owners");
      render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
      await user.click(screen.getByRole("tab", { name: /trades/i }));
      expect(window.location.search).toBe("?tab=owners");
    });
  });

  it("leads the Outlook tab with the Assets pillar, not a second model", async () => {
    const user = userEvent.setup();
    render(<OwnerDeepDive leagueId="L" detail={DETAIL_WITH_OUTLOOK} />);
    await user.click(screen.getByRole("tab", { name: /outlook/i }));
    expect(screen.getByTestId("assets-ledger-head")).toBeInTheDocument();
    expect(screen.getByText(/What the Assets pillar is made of/)).toBeInTheDocument();
    // The retired Strength x Trajectory receipt is gone entirely.
    expect(screen.queryByTestId("window-section")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Strength score|Trajectory score/);
  });

  it("lights the derived stage on the ladder and nothing else", async () => {
    const user = userEvent.setup();
    const { container } = render(<OwnerDeepDive leagueId="L" detail={DETAIL_WITH_OUTLOOK} />);
    await user.click(screen.getByRole("tab", { name: /outlook/i }));
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(1);
    expect(screen.getByText("Contending").getAttribute("data-on")).toBe("true");
  });

  it("shows the Outlook tab only when outlook is present", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    expect(screen.queryByRole("tab", { name: /outlook/i })).not.toBeInTheDocument();

    rerender(<OwnerDeepDive leagueId="L" detail={DETAIL_WITH_OUTLOOK} />);
    const outlookTab = screen.getByRole("tab", { name: /outlook/i });
    expect(outlookTab).toBeInTheDocument();
    await user.click(outlookTab);
    expect(screen.getAllByText("Contending").length).toBeGreaterThan(0);
  });

  describe("hero driver/drag line", () => {
    it("renders carried-by/dragged-by from the rating breakdown", () => {
      const detail: OwnerDetailResp = {
        ...DETAIL,
        franchise_rating: {
          ...DETAIL.franchise_rating!,
          pillars: {
            results: {
              weight: 0.5, z: 0, contribution: 40,
              signals: {
                championships: { raw: 2, z: 1.5, weight: 0.4, contribution: 42 },
                lineup_skill: { raw: 0.9, z: -1.2, weight: 0.3, contribution: -31 },
              },
            },
          },
        },
      };
      render(<OwnerDeepDive leagueId="L" detail={detail} />);
      /* The hero's carried-by/dragged-by line is gone — the Overview tab names
       * the same thing with the contributions attached ("Championships carries
       * the grade"), which is strictly more information than a bare label in
       * the masthead. `ratingDrivers` is still the source for that sentence, so
       * the derivation is asserted where it now renders. */
      expect(screen.getAllByText(/Championships/i).length).toBeGreaterThan(0);
    });

    it("renders no driver/drag claim in the hero when no signal crosses the noise floor", () => {
      render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
      expect(screen.queryByText(/carried by/i)).toBeNull();
      expect(screen.queryByText(/dragged by/i)).toBeNull();
    });
  });

  describe("owner receipt button", () => {
    it("copies the claim for the current tab + filter", async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText }, share: undefined });
      render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
      // Switch to Trades and filter to '23 (chip labeled '23 exists in DETAIL).
      await userEvent.click(screen.getByRole("tab", { name: "Trades" }));
      await userEvent.click(screen.getByRole("button", { name: "'23" }));
      await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
      const text = writeText.mock.calls[0][0] as string;
      expect(text).toContain("Alice's 2023 trades:");
      expect(text).toContain("/league/L/owner/u_a?tab=trades&year=2023");
      vi.unstubAllGlobals();
    });
  });
});
