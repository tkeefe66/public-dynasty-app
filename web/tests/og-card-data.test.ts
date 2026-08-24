import { describe, it, expect } from "vitest";
import {
  tradeCard, ownerCard, leagueCard, leaderboardCard, fallbackCard,
} from "@/lib/og-card-data";
import { PRODUCT_NAME } from "@/lib/brand";

// Numbers mirror Agate System.dc.html Fig. 8.1 exactly, so the fixture
// doubles as a sanity check against the drawn reference.
const jacobs = {
  label: "Josh Jacobs", kind: "player", player_id: "p1", ktc: 10000,
  production_total: 546.0, production_regular: 412.4, production_playoff: 96.2, production_toilet: 0,
  production_started: 546,
};
const barkley = {
  label: "Saquon Barkley", kind: "player", player_id: "p2", ktc: 6060,
  production_total: 164.0, production_regular: 108.2, production_playoff: 0, production_toilet: 0,
  production_started: 164,
};

const trade = {
  league_id: "L", trade_id: "t1", date: "2025-11-07", week: 10, season: 2025,
  league_name: "DyNASTY", story: { verdict: "tkeefe6689 fleeced Bobster565.", body: "" },
  sides: [
    {
      user_id: "u_t", owner_name: "tkeefe6689", received: [], given: [], breakdown: [jacobs],
      snapshot_ktc_swing: 4632, production_total: 546, production_regular: 412.4, production_playoff: 96.2,
      production_toilet: 0, at_trade_ktc_swing: null, aged_ktc_swing: null, at_trade_approx: false,
      at_trade_snapshot_date: null,
    },
    {
      user_id: "u_b", owner_name: "Bobster565", received: [], given: [], breakdown: [barkley],
      snapshot_ktc_swing: -4632, production_total: 164, production_regular: 108.2, production_playoff: 0,
      production_toilet: 0, at_trade_ktc_swing: null, aged_ktc_swing: null, at_trade_approx: false,
      at_trade_snapshot_date: null,
    },
  ],
  winners_by_lens: { value: "u_t", total: "u_t", regular: "u_t", playoff: "u_t", toilet: null },
  margins_by_lens: { value: 3940, total: 382, regular: 304.2, playoff: 96.2, toilet: null },
  call: "unanimous",
  lens_tally: "4-0",
  lopsidedness: 0.8,
} as any;

describe("tradeCard", () => {
  it("shows each side's REALIZED total (breakdown-derived) — never the swing on both sides", () => {
    const c = tradeCard(trade);
    expect(c.kind).toBe("trade");
    expect(c.colA).toBe("tkeefe6689");
    expect(c.colB).toBe("Bobster565");
    // Absolute per-side totals, matching the trade page's "Total realized"
    // rows (TradeStatTable.realizedTotals) — not a repeated swing figure.
    const value = c.rows.find((r) => r.lens === "value")!;
    expect([value.a, value.b]).toEqual([10000, 6060]);
    const total = c.rows.find((r) => r.lens === "total")!;
    expect([total.a, total.b]).toEqual([546, 164]);
    const playoff = c.rows.find((r) => r.lens === "playoff")!;
    expect([playoff.a, playoff.b]).toEqual([96.2, 0]);
    expect(c.rows.map((r) => r.label)).toEqual(["Value", "Total", "Reg", "Playoff", "Toilet"]);
  });

  it("reads the ruling straight off winners_by_lens/margins_by_lens/call — never recomputes", () => {
    const c = tradeCard(trade);
    expect(c.winnerCol).toBe("a");
    expect(c.ruling.badge).toBe("Lopsided"); // lopsidedness 0.8 >= 0.6
    expect(c.ruling.note).toContain("tkeefe6689");
    expect(c.ruling.note).toContain("+3,940 value");
  });

  it("uses the verdict when present, falls back to 'A vs B' otherwise", () => {
    expect(tradeCard(trade).headline).toBe("tkeefe6689 fleeced Bobster565.");
    expect(tradeCard({ ...trade, story: null }).headline).toBe("tkeefe6689 vs Bobster565");
  });

  it("names no winner column when the call is split or none", () => {
    const split = { ...trade, call: "split", lens_tally: "2-2" };
    expect(tradeCard(split).winnerCol).toBeNull();
    expect(tradeCard(split).ruling.badge).toBe("Split · 2-2");

    const none = { ...trade, call: "none", winners_by_lens: { value: null, total: null, regular: null, playoff: null, toilet: null } };
    expect(tradeCard(none).winnerCol).toBeNull();
    expect(tradeCard(none).ruling.badge).toBe("Too close");
  });

  it("footer carries the brand and the exact trade date", () => {
    const c = tradeCard(trade);
    expect(c.footer.left).toBe(PRODUCT_NAME);
    expect(c.footer.right).toBe("Nov 7, 2025");
  });
});

describe("ownerCard", () => {
  const base = {
    league_id: "L", user_id: "u_t", owner: { user_id: "u_t", owner_name: "tkeefe6689" },
    totals_by_lens: { ktc: 8200, production: 140.2, regular: 90, playoff: 12, toilet: 0 },
    career_arc: [{ season: 2024, trades: 3 } as any, { season: 2025, trades: 5 } as any],
    trades: [], best_trade_id: "t1", worst_trade_id: "t9",
  } as any;

  it("surfaces the Franchise Rating hero + net value / points / trades rows", () => {
    const c = ownerCard({
      ...base,
      franchise_rating: { letter: "A", rating: 1688, rank: 2, of: 12, trend: 1, pillars: {} },
      track_record: { seasons: [], titles: 1, runner_ups: 0, playoff_appearances: 5, seasons_played: 6, best_finish: 1, career_wins: 0, career_losses: 0, career_ties: 0 },
    }, "DyNASTY");
    expect(c.kind).toBe("owner");
    expect(c.name).toBe("tkeefe6689");
    expect(c.rating).toEqual({ letter: "A", tone: "pos", rank: 2, of: 12, value: 1688 });
    expect(c.rows.map((r) => r.label)).toEqual([
      "Net trade value", "Regular season points", "Playoff points", "Trades",
    ]);
    expect(c.rows.find((r) => r.label === "Trades")!.value).toBe(8);
    expect(c.footer.right).toBe("1 title · 5 playoff trips");
  });

  it("omits the rating block rather than inventing one when franchise_rating is absent", () => {
    const c = ownerCard(base, "DyNASTY");
    expect(c.rating).toBeNull();
    expect(c.footer.right).toBe("8 trades"); // falls back to real trade count, not fabricated record
  });
});

describe("leagueCard", () => {
  it("lists the top-3 standings by net Trade Value, signed", () => {
    const c = leagueCard({
      league: { name: "DyNASTY", season: 2025, total_rosters: 12 },
      standings: [
        { rank: 1, owner: { owner_name: "A" }, net_ktc: 5000, trades: 4 },
        { rank: 2, owner: { owner_name: "B" }, net_ktc: 3000, trades: 2 },
        { rank: 3, owner: { owner_name: "C" }, net_ktc: 1000, trades: 7 },
        { rank: 4, owner: { owner_name: "D" }, net_ktc: -200, trades: 1 },
      ],
    } as any);
    expect(c.kind).toBe("league");
    expect(c.name).toBe("DyNASTY");
    expect(c.rows.map((r) => r.name)).toEqual(["A", "B", "C"]);
    expect(c.subhead).toContain("12 managers");
    expect(c.footer.right).toBe("Season 2025");
    expect(c.nameplateSize).toBeGreaterThan(0);
  });
});

describe("fallbackCard", () => {
  it("never throws and carries the app's own brand string", () => {
    expect(fallbackCard("DyNASTY").eyebrow).toBe(PRODUCT_NAME);
    expect(fallbackCard("DyNASTY").title).toBe("DyNASTY");
    expect(fallbackCard().title).toBe("DyNASTY trade grader");
  });
});

describe("leaderboardCard", () => {
  const gm = (rank: number, name: string, rating: number, letter: string) => ({
    rank, user_id: name, owner: { user_id: name, owner_name: name },
    rating, letter, pillars: {},
    trend: 0, trades: 0, net_ktc: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
  });

  it("lists the top GMs, appends the last-place row on its own ink rule, no crown/bucket", () => {
    const resp = {
      league_id: "L", scope: "all", generated_at: "2026-01-01T00:00:00Z",
      rows: [
        gm(1, "Alice", 1840, "A"), gm(2, "Bob", 1600, "A"), gm(3, "Carol", 1550, "B"),
        gm(4, "Dave", 1500, "B"), gm(5, "Erin", 1400, "C"), gm(6, "Frank", 1200, "D"),
        gm(7, "Gina", 900, "F"),
      ],
    } as any;
    const c = leaderboardCard(resp, "DyNASTY", "week 9");
    expect(c.kind).toBe("leaderboard");
    expect(c.name).toBe("DyNASTY");
    expect(c.eyebrow).toBe("Franchise ratings · all-time");
    expect(c.footer.right).toBe("as of week 9");
    expect(c.rows.map((r) => r.name)).toEqual(
      ["Alice", "Bob", "Carol", "Dave", "Erin", "Gina"]);
    expect(c.rows[0].rating).toBe(1840);
    expect(c.rows[0].tone).toBe("pos"); // A
    const gina = c.rows[c.rows.length - 1];
    expect(gina.name).toBe("Gina");
    expect(gina.last).toBe(true);
    expect(gina.tone).toBe("neg"); // F
  });

  it("does not duplicate last place when it is already in the top rows", () => {
    const resp = {
      league_id: "L", scope: "2025", generated_at: "2026-01-01T00:00:00Z",
      rows: [gm(1, "Alice", 1800, "A"), gm(2, "Bob", 1500, "B"), gm(3, "Carol", 1200, "C")],
    } as any;
    const c = leaderboardCard(resp, "DyNASTY");
    expect(c.rows.map((r) => r.name)).toEqual(["Alice", "Bob", "Carol"]);
    expect(c.rows[2].last).toBe(true);
    expect(c.footer.right).toBe("2025");
  });
});
