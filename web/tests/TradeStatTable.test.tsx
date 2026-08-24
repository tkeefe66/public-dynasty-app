import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { TradeStatTable, realizedTotals, StatTotals } from "@/components/TradeStatTable";
import { AssetLine, LensMargins, LensWinners } from "@/lib/types";

const player = (label: string, p: Partial<AssetLine>): AssetLine => ({
  label, kind: "player", player_id: label, ktc: 0,
  production_total: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
  production_started: 0,
  ...p,
});

const rows: AssetLine[] = [
  player("Adams", { ktc: 4200, production_total: 90.1, production_regular: 60, production_playoff: 20, production_toilet: 0, production_started: 70 }),
  player("Goedert", { ktc: 2100, production_total: 70, production_regular: 40, production_playoff: 10, production_toilet: 0, production_started: 55 }),
  { label: "2027 1st", kind: "pick", player_id: null, ktc: 1500,
    production_total: 0, production_regular: 0, production_playoff: 0, production_toilet: 0, production_started: 0 },
];
const totals: StatTotals = { ktc: 7800, total: 160.1, regular: 100, playoff: 30, toilet: 0, started: 0 };

const NO_WINNERS: LensWinners = { value: null, total: null, regular: null, playoff: null, toilet: null };
const NO_MARGINS: LensMargins = { value: null, total: null, regular: null, playoff: null, toilet: null };

describe("TradeStatTable", () => {
  it("renders a row per asset with the owner name", () => {
    render(
      <TradeStatTable ownerName="ChocGummyBear" userId="u1" rows={rows} totals={totals}
                      winnersByLens={NO_WINNERS} marginsByLens={NO_MARGINS} />,
    );
    expect(screen.getByText("ChocGummyBear")).toBeTruthy();
    expect(screen.getAllByText("Adams").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Goedert").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2027 1st").length).toBeGreaterThan(0);
  });

  it("shows the fixed column order: Received · Value · Total · Started · Reg · Playoff · Toilet", () => {
    render(
      <TradeStatTable ownerName="x" userId="u1" rows={rows} totals={totals}
                      winnersByLens={NO_WINNERS} marginsByLens={NO_MARGINS} />,
    );
    /* Was `.ruled > *` — the first row of the striped ground. That ground is
     * retired; the head row is now a Panel's own head Row, so the query moves
     * with it.
     *
     * STARTED JOINED THE FIVE, deliberately, and it sits between Total and the
     * phase splits because that is a narrowing sequence: everything the haul
     * scored, then the part actually deployed, then that part by phase.
     *
     * It is NOT a sixth lens. The API still computes `margins_by_lens` and
     * `winners_by_lens` over five, the Scoreboard still says FIVE LENSES, and
     * the totals row leaves Started plain ink because it has no winner to
     * colour. The order below is still fixed vocabulary and must not drift. */
    const header = document.querySelector("[data-testid='stat-head']")!;
    expect(header.textContent).toBe("ReceivedValueTotalStartedRegPlayoffToilet");
  });

  it("sorts picks after players", () => {
    render(
      <TradeStatTable ownerName="x" userId="u1" rows={rows} totals={totals}
                      winnersByLens={NO_WINNERS} marginsByLens={NO_MARGINS} />,
    );
    const labels = screen.getAllByText(/^(Adams|Goedert|2027 1st)$/).map((e) => e.textContent);
    expect(labels.indexOf("2027 1st")).toBeGreaterThan(labels.indexOf("Adams"));
  });

  it("shows a dash for a pick's point columns", () => {
    render(
      <TradeStatTable ownerName="x" userId="u1" rows={[rows[2]]} totals={totals}
                      winnersByLens={NO_WINNERS} marginsByLens={NO_MARGINS} />,
    );
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("tags a kept on-roster player ON ROSTER and an unresolved pick UNRESOLVED", () => {
    const kept = player("Puka", { ktc: 100, production_total: 10, terminal_state: "on_roster" });
    render(
      <TradeStatTable ownerName="x" userId="u1" rows={[kept, rows[2]]} totals={totals}
                      winnersByLens={NO_WINNERS} marginsByLens={NO_MARGINS} />,
    );
    // Desktop grid renders each tag once; mobile rules duplicate them (mobile
    // hidden via CSS, same convention as TradeScoreboard.test.tsx).
    expect(screen.getAllByText("ON ROSTER").length).toBeGreaterThan(0);
    expect(screen.getAllByText("UNRESOLVED").length).toBeGreaterThan(0);
  });

  it("closing row: colors the winning side's lens pos, the losing side ink, and an unscored lens dim", () => {
    const winnersByLens: LensWinners = { value: "u1", total: "u2", regular: null, playoff: null, toilet: null };
    const marginsByLens: LensMargins = { value: 500, total: 20, regular: null, playoff: null, toilet: null };
    render(
      <TradeStatTable ownerName="x" userId="u1" rows={rows} totals={totals}
                      winnersByLens={winnersByLens} marginsByLens={marginsByLens} />,
    );
    // Desktop's "Total realized" occurrence is first in document order.
    const totalRow = screen.getAllByText("Total realized")[0].closest("div")!.parentElement!;
    const valueCell = within(totalRow).getByText("7,800");
    const totalCell = within(totalRow).getByText("160.1");
    const regCell = within(totalRow).getByText("100.0");
    expect(valueCell.className).toContain("text-pos"); // u1 won value
    expect(totalCell.className).toContain("text-ink"); // u2 won total — plain ink for u1
    expect(regCell.className).toContain("text-dim"); // unscored (margin null)
  });
});

// ── realizedTotals: the same reading the backend's margins_by_lens uses ────

describe("realizedTotals — reconciliation with margins_by_lens", () => {
  it("a kept asset contributes its own line", () => {
    const t = realizedTotals([
      player("Bijan", { ktc: 7500, production_total: 41.2, production_regular: 30, production_playoff: 9, production_toilet: 2 }),
    ]);
    expect(t).toEqual({ ktc: 7500, total: 41.2, regular: 30, playoff: 9, toilet: 2, started: 0 });
  });

  it("a flipped asset contributes what it became, not its own (empty) line", () => {
    const flipped: AssetLine = {
      label: "2025 1st", kind: "pick", player_id: null, ktc: 1500,
      production_total: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
      production_started: 0,
      flip: {
        to_owner: "Other", trade_id: null, league_id: null, date: null,
        became: [
          player("PlayerA", { ktc: 2000, production_total: 60, production_regular: 40, production_playoff: 20, production_toilet: 0 }),
          player("PlayerB", { ktc: 1500, production_total: 40, production_regular: 30, production_playoff: 10, production_toilet: 0 }),
        ],
      },
    };
    const t = realizedTotals([flipped]);
    expect(t).toEqual({ ktc: 3500, total: 100, regular: 70, playoff: 30, toilet: 0, started: 0 });
  });

  /** A subtotal is only a subtotal when it sums more than one thing.
   *
   *  Shipped bug: the guard tested `rows.length === 1` (did the SIDE receive one
   *  asset?) when the question is whether the BECAME GROUP has one. A real trade
   *  showed it — Oliver received two assets, so the guard stayed quiet, and the
   *  flip of Chris Olave resolved to a single player:
   *
   *      Chris Olave  FLIPPED →
   *        traded to Cormac · May 2, 2026 → became
   *        2026 1st → Emmett Johnson   2,559  0.0 …
   *        TOTAL                       2,559  0.0 …   ← the same row again
   */
  const flipTo = (became: AssetLine[]): AssetLine => ({
    label: "2026 1st", kind: "pick", player_id: "pick1", ktc: 0,
    production_total: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
    production_started: 0,
    flip: { to_owner: "Cormac", trade_id: null, league_id: null, date: null, became },
  });
  const kept = player("Stribling", { ktc: 3353 });

  it("omits the became subtotal when the flip resolved to ONE asset", () => {
    render(
      <TradeStatTable ownerName="Oliver" userId="u1"
                      rows={[flipTo([player("Emmett Johnson", { ktc: 2559 })]), kept]}
                      totals={{ ktc: 5912, total: 0, regular: 0, playoff: 0, toilet: 0, started: 0 }}
                      winnersByLens={NO_WINNERS} marginsByLens={NO_MARGINS} />,
    );
    // The became row itself is present...
    expect(screen.getAllByText("Emmett Johnson").length).toBeGreaterThan(0);
    // ...but nothing restates it. Only the panel's own closing row remains.
    expect(screen.queryAllByText("total")).toHaveLength(0);
    expect(screen.getAllByText(/Total realized/i).length).toBeGreaterThan(0);
  });

  it("keeps the became subtotal when the flip resolved to TWO assets", () => {
    render(
      <TradeStatTable ownerName="Oliver" userId="u1"
                      rows={[flipTo([player("A", { ktc: 100 }), player("B", { ktc: 200 })]), kept]}
                      totals={{ ktc: 3653, total: 0, regular: 0, playoff: 0, toilet: 0, started: 0 }}
                      winnersByLens={NO_WINNERS} marginsByLens={NO_MARGINS} />,
    );
    // Here it earns its place: it is the only figure saying what that one
    // flipped asset became in aggregate, and it is repeated nowhere else.
    expect(screen.getAllByText("total").length).toBeGreaterThan(0);
  });

  it("two sides' realized totals reproduce a hand-computed margin per lens", () => {
    // Winner: one kept asset. Loser: a flipped pick whose became-set is worse.
    const winnerRows: AssetLine[] = [
      player("Nabers", { ktc: 7900, production_total: 546.0, production_regular: 412.4, production_playoff: 96.2, production_toilet: 0 }),
    ];
    const loserRows: AssetLine[] = [
      player("Achane", { ktc: 5820, production_total: 164.0, production_regular: 108.2, production_playoff: 0, production_toilet: 0, terminal_state: "dropped" }),
    ];
    const winnerTotals = realizedTotals(winnerRows);
    const loserTotals = realizedTotals(loserRows);
    // These are exactly the margins the stamp/scoreboard would show for this pair.
    expect(winnerTotals.ktc - loserTotals.ktc).toBeCloseTo(2080, 5);
    expect(winnerTotals.total - loserTotals.total).toBeCloseTo(382, 5);
    expect(winnerTotals.regular - loserTotals.regular).toBeCloseTo(304.2, 5);
    expect(winnerTotals.playoff - loserTotals.playoff).toBeCloseTo(96.2, 5);
  });
});
