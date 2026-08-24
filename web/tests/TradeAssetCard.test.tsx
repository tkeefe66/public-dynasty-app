import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { TradeStatTable } from "@/components/TradeStatTable";
import type { AssetLine, LensMargins, LensWinners } from "@/lib/types";

/**
 * The PHONE branch of the trade stat table (followup C9).
 *
 * This branch had no coverage at all — it was rewritten from a row-per-metric
 * stack into cards and the whole suite stayed green, which is the same shape of
 * hole as the e2e specs that skipped every case and exited 0. jsdom renders both
 * branches (there is no media query), so these tests reach the cards by their
 * own controls rather than by width.
 *
 * What they hold down:
 *  1. COLLAPSED BY DEFAULT. Assets are sorted by value, so opening the first
 *     card would always expand the biggest one and make a claim by accident.
 *  2. A FLIPPED ASSET HAS NO CONTROL. It carries no figures of its own, so
 *     there is nothing to open and a chevron would promise detail that does not
 *     exist.
 *  3. THE TOTAL NEVER COLLAPSES. "Figures reconcile" is one of the four rules
 *     that survived Agate; a total behind a tap cannot be checked against the
 *     cards above it.
 */
const player = (label: string, p: Partial<AssetLine>): AssetLine => ({
  label, kind: "player", player_id: label, ktc: 0,
  production_total: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
  production_started: 0,
  ...p,
});

const ADAMS = player("Adams", {
  ktc: 4200, production_total: 90.1, production_regular: 60, production_playoff: 20,
  production_toilet: 0, production_started: 70,
});
const PICK: AssetLine = {
  label: "2027 1st", kind: "pick", player_id: null, ktc: 1500,
  production_total: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
  production_started: 0,
};
const TOTALS = { ktc: 5700, total: 90.1, regular: 60, playoff: 20, toilet: 0, started: 0 };
const NO_WINNERS: LensWinners = { value: null, total: null, regular: null, playoff: null, toilet: null };
const NO_MARGINS: LensMargins = { value: null, total: null, regular: null, playoff: null, toilet: null };

function renderTable(rows: AssetLine[], totals = TOTALS) {
  return render(
    <TradeStatTable ownerName="Oliver" userId="u1" rows={rows} totals={totals}
                    winnersByLens={NO_WINNERS} marginsByLens={NO_MARGINS} />,
  );
}

/** The phone branch. jsdom renders BOTH branches (no media queries), so every
 *  query here is scoped to the card list — an unscoped one reads the desktop
 *  ledger instead, which is exactly how the first totals assertion passed
 *  against the wrong element. */
const cards = () => within(screen.getByTestId("stat-cards"));

/** The card disclosure for an asset, by the accessible name of its trigger. */
const trigger = (name: string) =>
  cards().getAllByRole("button", { name: new RegExp(name, "i") })[0];

describe("trade asset cards (phone)", () => {
  it("starts every asset collapsed", () => {
    renderTable([ADAMS, PICK]);
    for (const t of cards().getAllByRole("button", { expanded: false })) {
      expect(t.getAttribute("aria-expanded")).toBe("false");
    }
    expect(cards().queryAllByRole("button", { expanded: true })).toHaveLength(0);
  });

  it("opens and closes one card without touching the others", () => {
    renderTable([ADAMS, PICK]);
    const adams = trigger("Adams");
    const pick = trigger("2027 1st");

    fireEvent.click(adams);
    expect(adams.getAttribute("aria-expanded")).toBe("true");
    expect(pick.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(adams);
    expect(adams.getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps the hidden metrics in the DOM, hidden — not unmounted", () => {
    // Find-in-page and assistive tech still reach them, and the collapse stays
    // a display concern rather than a data one.
    renderTable([ADAMS]);
    const t = trigger("Adams");
    const body = document.getElementById(t.getAttribute("aria-controls")!)!;
    expect(body).toBeTruthy();
    expect(body.hasAttribute("hidden")).toBe(true);
    expect(body.textContent).toMatch(/Playoff/);

    fireEvent.click(t);
    expect(body.hasAttribute("hidden")).toBe(false);
  });

  it("gives a flipped asset NO disclosure, and shows its journey unconditionally", () => {
    const flipped: AssetLine = {
      label: "Chris Olave", kind: "player", player_id: "olave", ktc: 0,
      production_total: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
      production_started: 0,
      flip: {
        to_owner: "Cormac", trade_id: null, league_id: null, date: null,
        became: [player("Emmett Johnson", { ktc: 2559 })],
      },
    };
    renderTable([flipped]);

    // No trigger names the flipped asset — it has no figures to reveal.
    expect(
      cards().queryAllByRole("button", { name: /Chris Olave/i }),
    ).toHaveLength(0);
    // Its journey line is the card's content, so it is visible with no tap.
    expect(cards().getAllByText(/traded to/i).length).toBeGreaterThan(0);
    // What it became is a card of its own, and that one DOES open.
    expect(trigger("Emmett Johnson")).toBeTruthy();
  });

  it("never collapses the total, and shows all five metrics on it", () => {
    renderTable([ADAMS, PICK]);
    // "Total realized" is not a button at any point.
    expect(cards().queryAllByRole("button", { name: /Total realized/i })).toHaveLength(0);

    const list = screen.getByTestId("stat-cards");
    const text = list.lastElementChild!.textContent ?? "";
    for (const label of ["Total", "Reg", "Playoff", "Toilet"]) {
      expect(text).toContain(label);
    }
    // And the headline figure is the Trade Value total, so the card reconciles
    // against the asset cards above it without a tap.
    expect(text).toMatch(/5,700|5700/);
  });

  it("puts the asset's own name in the trigger, not its provenance", () => {
    // At 390px a name plus a state tag plus a five-figure number fills the
    // line; prefixing "2026 1st pick →" truncated the player, which is the one
    // word the card exists to say. Provenance moved into the body.
    const fromPick = player("Makai Lemon", { ktc: 4987, from_pick: "2026 1st" });
    renderTable([fromPick]);
    const t = trigger("Makai Lemon");
    expect(t.textContent).not.toMatch(/2026 1st/);

    fireEvent.click(t);
    const body = document.getElementById(t.getAttribute("aria-controls")!)!;
    expect(body.textContent).toMatch(/from 2026 1st pick/i);
  });

  it("dashes an unresolved pick's production rather than printing 0.0", () => {
    renderTable([PICK]);
    const t = trigger("2027 1st");
    fireEvent.click(t);
    const body = document.getElementById(t.getAttribute("aria-controls")!)!;
    // Five now, not four: Started joined the metrics an unresolved pick has
    // none of. Value is the headline, so it is not among them.
    expect(within(body).getAllByText("—").length).toBe(5);
  });

  /* ---- which metric a card leads with -------------------------------- */

  const SCORED: LensMargins = { value: 880, total: 141.2, regular: 120, playoff: 21.2, toilet: null };

  function renderScored(rows: AssetLine[]) {
    return render(
      <TradeStatTable ownerName="Oliver" userId="u1" rows={rows}
                      totals={{ ktc: 4200, total: 90.1, regular: 60, playoff: 20, toilet: 0, started: 74.5 }}
                      winnersByLens={NO_WINNERS} marginsByLens={SCORED} />,
    );
  }

  it("leads with STARTED POINTS once the trade has produced", () => {
    // A trade is settled on the field, not on today's market. `started` is
    // starters-only, so a player who produced from the bench does not flatter
    // the headline.
    renderScored([{ ...ADAMS, production_started: 74.5 }]);
    const t = trigger("Adams");
    expect(t.textContent).toMatch(/Started Points/i);
    expect(t.textContent).toContain("74.5");
    // The bench-inclusive total is a different number and must not be the one
    // in the headline slot.
    expect(t.textContent).not.toContain("90.1");
  });

  it("leads with TRADE VALUE before anything has played", () => {
    // Every production figure is 0.0 pre-season, so "0.0 Started Points" would
    // headline the absence of information. The ruling stamp already calls this
    // state VALUE ONLY; the card agrees with it rather than inventing a rule.
    renderTable([ADAMS]);
    const t = trigger("Adams");
    expect(t.textContent).toMatch(/Trade value/i);
    expect(t.textContent).toContain("4,200");
  });

  it("keeps Trade Value on the card once production leads", () => {
    // Demoted to the meta line, never dropped — it is still the one true
    // zero-sum swing.
    renderScored([{ ...ADAMS, production_started: 74.5 }]);
    const t = trigger("Adams");
    const body = document.getElementById(t.getAttribute("aria-controls")!)!;
    expect(body.textContent).toContain("4,200");
    expect(body.textContent).toMatch(/Value/);
  });

  it("decides the lead per TRADE, not per side", () => {
    // `marginsByLens` is trade-level. If this read a side's own figures, a side
    // that scored nothing would lead with Trade Value while its opponent led
    // with points — two different headline metrics on one screen.
    renderScored([{ ...ADAMS, production_started: 0, production_total: 0 }]);
    expect(trigger("Adams").textContent).toMatch(/Started Points/i);
  });
});
