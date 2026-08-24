import { describe, it, expect } from "vitest";
import { ownerReceipt, ownerPath, tradeReceipt } from "../lib/receipts";
import { OwnerDetailResp, TradeDetailResp } from "../lib/types";

const DETAIL = {
  league_id: "L", user_id: "u_a",
  owner: { user_id: "u_a", owner_name: "Mike", team_name: "Team M" },
  totals_by_lens: { ktc: 600, production: 70, regular: 60, playoff: 20, toilet: 5 },
  career_arc: [],
  trades: [
    { trade_id: "t1", date: "2023-10-01", season: 2023, week: 4, counterparties: [{ user_id: "u_b", owner_name: "Dave" }], assets_short: "X", swing_ktc: -800, swing_prod: 10, swing_regular: 5, swing_playoff: 0, swing_toilet: 0 },
    { trade_id: "t2", date: "2023-11-01", season: 2023, week: 9, counterparties: [{ user_id: "u_b", owner_name: "Dave" }], assets_short: "Y", swing_ktc: -440, swing_prod: 4, swing_regular: 4, swing_playoff: 0, swing_toilet: 0 },
    { trade_id: "t3", date: "2024-09-12", season: 2024, week: 2, counterparties: [{ user_id: "u_c", owner_name: "Cara" }], assets_short: "Z", swing_ktc: 1840, swing_prod: 60, swing_regular: 50, swing_playoff: 15, swing_toilet: 3 },
  ],
  best_trade_id: null, worst_trade_id: null,
  franchise_rating: {
    letter: "B", rating: 1620, rank: 3, of: 11, trend: 1,
    pillars: { results: { weight: 0.5, z: 0, contribution: 40, signals: { championships: { raw: 2, z: 1.5, weight: 0.4, contribution: 42 } } } },
  },
  track_record: {
    seasons: [], titles: 2, runner_ups: 1, playoff_appearances: 5, seasons_played: 6,
    best_finish: 1, career_wins: 89, career_losses: 67, career_ties: 0,
  },
} as OwnerDetailResp;

describe("ownerReceipt", () => {
  it("overview: letter, rank, driver", () => {
    expect(ownerReceipt(DETAIL, "overview", "all")).toBe(
      "Mike: B franchise, 3rd of 11 — carried by Championships",
    );
  });
  it("trades with a year filter: sums that year's ledger rows", () => {
    expect(ownerReceipt(DETAIL, "trades", 2023)).toBe(
      "Mike's 2023 trades: -1,240 Trade Value across 2 deals",
    );
  });
  it("trades all-time: sums every row, singular/plural handled", () => {
    expect(ownerReceipt(DETAIL, "trades", "all")).toBe(
      "Mike's trades: +600 Trade Value across 3 deals",
    );
  });
  it("record: titles, record, best finish", () => {
    expect(ownerReceipt(DETAIL, "record", "all")).toBe(
      "Mike all-time: 2 titles, 89-67, best finish 1st",
    );
  });
  it("falls back to a neutral line when the rating is missing", () => {
    const cold = { ...DETAIL, franchise_rating: null } as OwnerDetailResp;
    expect(ownerReceipt(cold, "overview", "all")).toBe("Mike — franchise receipts");
  });
});

describe("ownerPath", () => {
  it("canonical URL rules match the page's query sync", () => {
    expect(ownerPath("L", "u_a", "overview", "all")).toBe("/league/L/owner/u_a");
    expect(ownerPath("L", "u_a", "trades", 2023)).toBe("/league/L/owner/u_a?tab=trades&year=2023");
    expect(ownerPath("L", "u_a", "trades", "all")).toBe("/league/L/owner/u_a?tab=trades");
    expect(ownerPath("L", "u_a", "record", 2023)).toBe("/league/L/owner/u_a?tab=record");
  });
});

describe("tradeReceipt", () => {
  const TRADE = {
    league_id: "L", trade_id: "t1", date: "2024-09-12", week: 2, season: 2024, league_name: "Dynasty",
    sides: [
      { user_id: "u_a", production_started: 104.2, received_ktc: 1200 },
      { user_id: "u_b", production_started: 56.4, received_ktc: 400 },
    ],
    owner_names: { u_a: "Mike", u_b: "Dave" },
    winner_user_id: "u_a",
    lopsidedness: 0.7,
    winners_by_lens: { value: "u_a", total: null, regular: null, playoff: null, toilet: null },
    margins_by_lens: { value: 800, total: null, regular: null, playoff: null, toilet: null },
  } as unknown as TradeDetailResp;

  it("names winner, started-points head-to-head, and the value-lens margin from margins_by_lens", () => {
    expect(tradeReceipt(TRADE)).toBe(
      "'24 W2 — Mike beat Dave: 104-56 started pts, +800 Trade Value",
    );
  });
  it("too-close trades get neutral copy", () => {
    const even = { ...TRADE, winner_user_id: null } as TradeDetailResp;
    expect(tradeReceipt(even)).toBe("'24 W2 — Mike vs Dave: 104-56 started pts");
  });
  it("guards against fewer than 2 sides, falling back to the when-label", () => {
    const noSides = { ...TRADE, sides: [] } as unknown as TradeDetailResp;
    expect(tradeReceipt(noSides)).toBe("'24 W2");
  });
  it("omits the Trade Value clause rather than recomputing when margins_by_lens is absent (pre-flip-ruling cache entry)", () => {
    const noLens = {
      ...TRADE, winners_by_lens: undefined, margins_by_lens: undefined,
    } as TradeDetailResp;
    expect(tradeReceipt(noLens)).toBe("'24 W2 — Mike beat Dave: 104-56 started pts");
  });
  it("omits the Trade Value clause when a flip means the value lens named a different winner than winner_user_id", () => {
    const flipped = {
      ...TRADE,
      winners_by_lens: { value: "u_b", total: null, regular: null, playoff: null, toilet: null },
      margins_by_lens: { value: 300, total: null, regular: null, playoff: null, toilet: null },
    } as TradeDetailResp;
    expect(tradeReceipt(flipped)).toBe("'24 W2 — Mike beat Dave: 104-56 started pts");
  });
});
