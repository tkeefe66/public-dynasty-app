import { render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { OutlookTab } from "@/components/ownerdeepdive/OutlookTab";
import type { OwnerDetailResp } from "@/lib/types";

function detail(over: Record<string, unknown> = {}): OwnerDetailResp {
  return {
    user_id: "uA",
    owner: { user_id: "uA", owner_name: "Tom" },
    unrated_reason: null,
    roster_rank: { rank: 3, of: 12 },
    draft_skill: { score: 0.4, rank: 4, of: 12 },
    franchise_rating: {
      letter: "A-", rating: 1688, rank: 2, of: 12, trend: 1,
      pillar_highlights: {},
      pillars: {
        results: { weight: 0.6, z: 0.84, contribution: 138, signals: {}, signal_ranks: {} },
        assets: {
          weight: 0.4, z: 1.12, contribution: 75,
          signals: {
            roster_value_share: { raw: 0.098, z: 1.4, weight: 0.45, contribution: 41 },
            young_core_share: { raw: 0.41, z: 1.8, weight: 0.35, contribution: 52 },
            draft_capital: { raw: 4200, z: -0.9, weight: 0.20, contribution: -18 },
          },
          signal_ranks: { roster_value_share: 3, young_core_share: 2, draft_capital: 10 },
        },
      },
    },
    outlook: {
      window: "Contending",
      results_z: 0.84, assets_z: 1.12, tilt: 0.28,
      assets_signal_ranks: { roster_value_share: 3, young_core_share: 2, draft_capital: 10 },
      age_profile: {
        avg_age_by_position: { RB: 26.5 },
        league_avg_age_by_position: { RB: 25.9 },
        overall_avg_age: 26, aging_risks: [], core_young: [],
      },
      draft_capital: {
        picks_by_season: { "2026": 2, "2027": 3 },
        picks_by_season_round: { "2026-2": 1, "2026-3": 1, "2027-1": 1, "2027-2": 1, "2027-4": 1 },
        net_vs_average: -1.8, status: "pick-poor", total_value: 4200,
      },
      draft_needs: [],
    },
    ...over,
  } as unknown as OwnerDetailResp;
}

describe("OutlookTab hero", () => {
  it("names the pillar, its weight and the grade in the kicker", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getByText(/Assets — 40% of your A−/)).toBeTruthy();
  });

  it("states the pillar's point contribution in the verdict line", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getByText(/\+75 rating points/)).toBeTruthy();
  });

  it("lights the derived stage on the ladder and nothing else", () => {
    const { container } = render(<OutlookTab detail={detail()} />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(1);
    expect(screen.getByText("Contending").getAttribute("data-on")).toBe("true");
  });

  it("shows both z's and the tilt as the receipt", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getByText(/Results z \+0\.84/)).toBeTruthy();
    expect(screen.getByText(/Assets z \+1\.12/)).toBeTruthy();
  });

  it("names the roster ahead of the trophy case for a positive tilt (assets_z > results_z)", () => {
    // Default fixture: tilt=0.28 (assets_z 1.12 - results_z 0.84).
    render(<OutlookTab detail={detail()} />);
    expect(
      screen.getByText(/Assets ahead of Results — the roster is ahead of the trophy case\./),
    ).toBeTruthy();
  });

  it("names the trophy case ahead of the roster for a negative tilt (assets_z < results_z)", () => {
    const base = detail();
    const d = detail({
      outlook: { ...(base.outlook as object), tilt: -0.28 } as never,
    });
    render(<OutlookTab detail={d} />);
    expect(
      screen.getByText(/Results ahead of Assets — the trophy case is ahead of the roster\./),
    ).toBeTruthy();
  });

  it("calls it level for a zero tilt", () => {
    const base = detail();
    const d = detail({
      outlook: { ...(base.outlook as object), tilt: 0 } as never,
    });
    render(<OutlookTab detail={d} />);
    expect(screen.getByText(/Results and Assets are level\./)).toBeTruthy();
  });

  it("renders an absence, not a fallback label, for an unrated owner", () => {
    const { container } = render(<OutlookTab detail={detail({
      franchise_rating: null,
      unrated_reason: "first_season",
      outlook: { ...(detail().outlook as object), window: null } as never,
    })} />);
    expect(container.querySelectorAll('[data-on="true"]')).toHaveLength(0);
    expect(screen.getByText(/first season/i)).toBeTruthy();
  });
});

describe("OutlookTab assets ledger", () => {
  it("gives Figure and Rank separate headed columns", () => {
    render(<OutlookTab detail={detail()} />);
    const head = screen.getByTestId("assets-ledger-head");
    expect(within(head).getByText("Figure")).toBeTruthy();
    expect(within(head).getByText("Rank")).toBeTruthy();
    // NOT the combined "9.8% · 3rd" run-on that was built and rejected.
    expect(screen.queryByText("9.8% · 3rd")).toBeNull();
  });

  it("renders Draft Capital's Figure as the raw value Rank ranks, never the pick count", () => {
    // Figure and Rank sit adjacent in one row and a reader takes them for two
    // readings of one quantity. `_stamp_signal_ranks` ranks the RAW Trade
    // Value, so Figure must be the raw too. Substituting the pick count
    // shipped rows reading "11 picks · 6th" above "10 picks · 1st" on the
    // reference league, and two owners both on "9 picks" ranked 5th and 9th.
    //
    // Mutation this catches: restoring the count branch. The fixture holds
    // raw 4200 and 2 + 3 = 5 future picks, so the two readings cannot be
    // confused for each other.
    render(<OutlookTab detail={detail()} />);
    expect(screen.getAllByText("4,200").length).toBeGreaterThan(0);
    expect(screen.queryByText("5 picks")).toBeNull();
  });

  it("reconciles: the visible rows sum to the total shown", () => {
    render(<OutlookTab detail={detail()} />);
    const rows = screen.getAllByTestId("assets-add");
    const sum = rows.reduce((a, n) => a + Number(n.textContent!.replace("−", "-")), 0);
    expect(sum).toBe(75);
    expect(screen.getByTestId("assets-total").textContent).toBe("+75");
  });

  it("renders EVERY assets signal, unfiltered — a noise floor would break the sum", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getAllByTestId("assets-add")).toHaveLength(3);
  });

  it("names the signal count and the pillar weight in the total row", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getAllByText(/Assets — three signals × 40% weight/).length).toBeGreaterThan(0);
  });

  it("keeps rendering when the rating is absent", () => {
    render(<OutlookTab detail={detail({ franchise_rating: null })} />);
    expect(screen.getByText(/Draft needs/)).toBeTruthy();
  });
});

/* ---------------------------------------------------------------------------
 * The narrow render. jsdom applies no stylesheet, so BOTH branches are in the
 * tree here and neither is laid out — these assert that every column survives
 * the split and that the two renders carry the same arithmetic, which is what
 * a test can actually prove. Whether the cards LOOK right at 390px is a human
 * check; grid layout does not exist in jsdom.
 * ------------------------------------------------------------------------ */
describe("OutlookTab assets ledger — narrow", () => {
  it("is a card stack, not a squeezed grid, and carries no second column template", () => {
    const { container } = render(<OutlookTab detail={detail()} />);
    const stack = container.querySelector(".min-\\[701px\\]\\:hidden");
    expect(stack).not.toBeNull();
    // The one grid template in this section is desktop-only: no `min-[701px]:`
    // -prefixed grid-cols anywhere, which is the shape that let a head row and
    // a body row hide different numbers of cells.
    expect(container.innerHTML).not.toMatch(/min-\[701px\]:grid-cols-/);
  });

  it("reconciles independently of the desktop ledger", () => {
    render(<OutlookTab detail={detail()} />);
    const cells = screen.getAllByTestId("assets-add-narrow");
    expect(cells).toHaveLength(3);
    const sum = cells.reduce((a, n) => a + Number(n.textContent!.replace("−", "-")), 0);
    expect(sum).toBe(75);
    expect(screen.getByTestId("assets-total-narrow").textContent).toBe("+75");
  });

  it("keeps Figure and Rank as labelled facts rather than dropping them", () => {
    render(<OutlookTab detail={detail()} />);
    expect(screen.getAllByText(/Figure/).length).toBeGreaterThan(1);
    expect(screen.getAllByText("9.8%").length).toBeGreaterThan(1);
    expect(screen.getAllByText("3rd").length).toBeGreaterThan(1);
  });

  it("says the rounding gap out loud in BOTH renders rather than picking a number", () => {
    // The pillar's own figure disagrees with the sum of its rounded signals.
    const d = detail();
    (d.franchise_rating!.pillars.assets as { contribution: number }).contribution = 76;
    render(<OutlookTab detail={d} />);
    expect(screen.getAllByText(/pillar above rounds to \+76/)).toHaveLength(2);
    // The totals still show the on-screen sum, not the pillar's figure.
    expect(screen.getByTestId("assets-total").textContent).toBe("+75");
    expect(screen.getByTestId("assets-total-narrow").textContent).toBe("+75");
  });
});
