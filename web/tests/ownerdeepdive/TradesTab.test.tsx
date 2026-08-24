import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { TradesTab } from "../../components/ownerdeepdive/TradesTab";
import type { OwnerDetailResp } from "../../lib/types";

/**
 * The phone cards on a franchise's trading record.
 *
 * The decision under test: a card LEADS WITH TOTAL POINTS, not Trade Value.
 * A card has one headline slot, and on a trading record the question is what
 * the deals produced on the field rather than what the assets are worth on the
 * market today. Trade Value is not dropped — it moves into the meta line.
 *
 * Worth stating because it is easy to "fix" back: the five-metric vocabulary
 * and its ORDER are contract (Trade Value · Total Points · Regular Season ·
 * Playoff · Toilet Bowl), and the desktop columns still follow it. Only the
 * card's headline departs, deliberately.
 *
 * Also note what Total Points IS — `production`, bench included, every week.
 * The started-only figures are the three phase metrics. There is no
 * started-only TOTAL on `OwnerTradeRow`, and this deliberately does not sum
 * the three phases into one: defensible arithmetic, but a new headline metric
 * appearing nowhere else in the app.
 */
const DETAIL: OwnerDetailResp = {
  league_id: "lg",
  user_id: "u1",
  owner: { user_id: "u1", owner_name: "Alice" },
  // started != regular + playoff + toilet (438.5 + 58.9 + 0 = 497.4): the
  // extra 12.0 is started points in weeks belonging to no phase — placement
  // games and eliminated weeks. Real on this league for 14 of 52 pairs.
  totals_by_lens: {
    ktc: 12034, production: 520.0, regular: 438.5, playoff: 58.9, toilet: 0,
    started: 509.4, start_pct: 509.4 / 520.0,
  },
  career_arc: [],
  best_trade_id: null,
  worst_trade_id: null,
  trades: [
    {
      trade_id: "t1", date: "2026-05-02", season: 2026, week: null,
      counterparties: [{ user_id: "u2", owner_name: "Bob" }],
      assets_short: "Chris Olave for 2026 1st",
      swing_ktc: 880, swing_prod: 150.0, swing_regular: 120.0,
      swing_playoff: 21.2, swing_toilet: 0, swing_started: 145.6,
      start_pct: 145.6 / 150.0,
    },
  ],
};

/** The phone branch. jsdom has no media queries, so both render — and both
 *  print all five figures, which is why asserting a figure is merely PRESENT
 *  proves nothing about which one leads. These target the headline slots. */
const lead = () => screen.getByTestId("trade-card-lead");
const totalsLead = () => screen.getByTestId("trades-totals-lead");

describe("TradesTab phone cards", () => {
  it("leads each trade with Started Points", () => {
    render(<TradesTab leagueId="lg" detail={DETAIL} yearFilter="all" onYearFilterChange={() => {}} />);
    // The headline slot holds the figure AND names it. Both halves matter: the
    // figure alone appears in the meta line and the desktop table too, so an
    // earlier version of this test passed while the card led with Trade Value.
    expect(lead().textContent).toContain("+145.6");
    expect(lead().textContent).toMatch(/Started Points/i);
    expect(lead().textContent).not.toMatch(/Trade value/i);
    expect(lead().textContent).not.toContain("+880");
    // Starters-only is NOT the bench-inclusive total.
    expect(lead().textContent).not.toContain("+150.0");
  });

  it("falls back to Total Points when the response predates the field", () => {
    // A cached response served before `swing_started` existed omits it.
    // Printing 0.0 would read as "these trades produced nothing".
    const old = {
      ...DETAIL,
      totals_by_lens: { ...DETAIL.totals_by_lens, started: undefined },
      trades: [{ ...DETAIL.trades[0], swing_started: undefined }],
    };
    render(<TradesTab leagueId="lg" detail={old} yearFilter="all" onYearFilterChange={() => {}} />);
    expect(lead().textContent).toContain("+150.0");
    expect(lead().textContent).toMatch(/Total Points/i);
  });

  it("keeps Trade Value on the card, demoted to the meta line", () => {
    // Demoted, not dropped: it is still the one true zero-sum swing.
    render(<TradesTab leagueId="lg" detail={DETAIL} yearFilter="all" onYearFilterChange={() => {}} />);
    const card = lead().closest("a") ?? lead().parentElement!.parentElement!;
    expect(card.textContent).toContain("+880");
  });

  it("leads the totals card with Started Points too", () => {
    render(<TradesTab leagueId="lg" detail={DETAIL} yearFilter="all" onYearFilterChange={() => {}} />);
    // The summary and the rows it sums must agree on what they lead with.
    expect(totalsLead().textContent).toContain("+509.4");
    expect(totalsLead().textContent).toMatch(/Started Points/i);
    expect(totalsLead().textContent).not.toContain("12,034");
  });

  it("carries exactly three facts per card — Value, Started %, Playoff", () => {
    /* A deliberate departure from "every column survives". This ledger was
     * 2,058px of a 3,889px tab at 390px — 158px per trade across 13 deals —
     * because six facts wrapped onto three lines.
     *
     * COUNTS the facts rather than reading textContent, and that matters: the
     * first version of this test asserted `not.toMatch(/\bReg\b/)` and passed
     * against a card that still rendered Reg, because in textContent the label
     * follows a digit ("21.2Reg") and `\b` needs a word/non-word transition.
     * A structural count cannot be fooled that way. */
    render(<TradesTab leagueId="lg" detail={DETAIL} yearFilter="all" onYearFilterChange={() => {}} />);
    const meta = screen.getByTestId("trade-card-meta");
    expect(meta.children).toHaveLength(3);

    const labels = Array.from(meta.children).map((c) => (c.textContent ?? "").trim());
    expect(labels[0]).toMatch(/^Value/);
    expect(labels[1]).toMatch(/^Started/);
    expect(labels[2]).toMatch(/^Playoff/);
  });

  it("keeps every metric on the totals card, so nothing leaves the tab", () => {
    // This is what makes trimming the rows allowable: the full set is still
    // stated once, at the top, on the card the rows sum to.
    render(<TradesTab leagueId="lg" detail={DETAIL} yearFilter="all" onYearFilterChange={() => {}} />);
    const totals = totalsLead().closest("div")!.parentElement!;
    const text = totals.textContent ?? "";
    for (const label of ["Started", "Value", "Reg", "Playoff", "Toilet"]) {
      expect(text).toMatch(new RegExp(label));
    }
  });

  it("shows the start rate — the bench-miss reading — as a whole percent", () => {
    // The gap between Started Points and Total Points IS this number; without
    // it the card states both figures and never names what their difference
    // means. 145.6 / 150.0 = 97.07% -> "97%".
    render(<TradesTab leagueId="lg" detail={DETAIL} yearFilter="all" onYearFilterChange={() => {}} />);
    const card = lead().closest("a") ?? lead().parentElement!.parentElement!;
    expect(card.textContent).toMatch(/Started\s*97%/);
  });

  it("prints NO start rate rather than 0% when nothing has played", () => {
    // 0% reads as "you benched everything" — the most damning reading of the
    // least information. The backend sends null; the card must stay silent.
    const unplayed = {
      ...DETAIL,
      totals_by_lens: { ...DETAIL.totals_by_lens, start_pct: undefined },
      trades: [{ ...DETAIL.trades[0], start_pct: null }],
    };
    render(<TradesTab leagueId="lg" detail={unplayed} yearFilter="all" onYearFilterChange={() => {}} />);
    // textContent, NOT queryByText: `Meta` puts the label and the value in
    // separate nodes, so a text query cannot match across them and passed even
    // when the component rendered "Started 0%".
    expect(document.body.textContent).not.toMatch(/Started\s*0\s*%/);
    expect(document.body.textContent).not.toMatch(/Started\s*\d/);
  });
});
