import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  listBets: vi.fn(),
  betsSummary: vi.fn(),
  createBet: vi.fn(),
  updateBet: vi.fn(),
}));

import { betsSummary, createBet, listBets, updateBet } from "@/lib/api";
import { BetsTab } from "@/components/bets/BetsTab";
import type { StandingRow } from "@/lib/types";

/**
 * ADDED IN REVIEW. `BetsTab.test.tsx`'s fixture is DEGENERATE for the one rule
 * that has no exceptions: every owner in it has either `cents_lost === 0` or
 * `cents_won === 0`, so `net = won − lost` collapses to `net = won` (or
 * `−lost`) and the identity is never exercised. Wiring the card headline to
 * `cents_won` instead of `net_cents` — or reverting Won/Lost to the W-L counts
 * the approved mock showed — passes every assertion there.
 *
 * This pins the arithmetic itself: it PARSES the three displayed figures back
 * out of the card and asserts headline === won − lost, with all three distinct.
 */

const owners = [
  { user_id: "u_ann", owner: { user_id: "u_ann", owner_name: "Ann" } },
  { user_id: "u_bob", owner: { user_id: "u_bob", owner_name: "Bob" } },
] as unknown as StandingRow[];

const ref = (uid: string, name: string) => ({ user_id: uid, owner_name: name });

const bet = {
  id: "b1",
  season: 2026,
  description: "Ann finishes above Bob",
  amount_cents: 20000,
  side_a: ref("u_ann", "Ann"),
  side_b: ref("u_bob", "Bob"),
  status: "open" as const,
  winner_owner_id: null,
  made_at: "2026-07-01",
  settled_at: null,
};

/** won $700, lost $200, net +$500 — three DIFFERENT figures, and a W-L-P
 *  record whose numbers cannot be confused with the money. */
const summary = {
  owners: [
    {
      owner: ref("u_ann", "Ann"),
      won: 3, lost: 1, pushed: 0,
      cents_won: 70000, cents_lost: 20000, net_cents: 50000,
      cents_at_stake: 20000, biggest_win_cents: 40000, worst_loss_cents: 20000,
    },
    {
      owner: ref("u_bob", "Bob"),
      won: 1, lost: 3, pushed: 0,
      cents_won: 20000, cents_lost: 70000, net_cents: -50000,
      cents_at_stake: 20000, biggest_win_cents: 20000, worst_loss_cents: 40000,
    },
  ],
};

beforeEach(() => {
  vi.mocked(listBets).mockResolvedValue({ bets: [bet] });
  vi.mocked(betsSummary).mockResolvedValue(summary);
  vi.mocked(createBet).mockReset();
  vi.mocked(updateBet).mockReset();
});

/** "$700" / "−$500" / "+$500" → cents. U+2212, per `formatSignedCents`. */
function parseMoney(text: string): number {
  const m = /^([+−-]?)\$([\d,]+(?:\.\d{2})?)$/.exec(text.trim());
  if (!m) throw new Error(`not a money figure: ${JSON.stringify(text)}`);
  const cents = Math.round(Number(m[2].replace(/,/g, "")) * 100);
  return m[1] === "−" || m[1] === "-" ? -cents : cents;
}

/** label → value for each `Meta` fact on a card. */
function factMap(card: HTMLElement): Record<string, string> {
  const out: Record<string, string> = {};
  card.querySelectorAll("span.whitespace-nowrap").forEach((n) => {
    const value = n.querySelector("b")?.textContent?.trim() ?? "";
    const label = (n.textContent ?? "").replace(value, "").trim();
    out[label] = value;
  });
  return out;
}

describe("bet leaderboard card reconciles", () => {
  for (const name of ["Ann", "Bob"]) {
    it(`${name}: the NET headline equals Won − Lost as displayed`, async () => {
      render(<BetsTab leagueId="L1" owners={owners} />);
      const cards = within(await screen.findByTestId("bet-leader-cards"));
      const card = cards.getByText(name).closest("div.rounded-panel") as HTMLElement;

      // The headline figure: the mono one, not the display-face Name beside it.
      const headline = parseMoney(
        card.querySelector("span.font-mono.text-name")?.textContent ?? "",
      );
      const f = factMap(card);

      // The facts under the headline must be MONEY, not the W-L counts.
      expect(parseMoney(f.Won) - parseMoney(f.Lost)).toBe(headline);
      // ...and the three figures must actually be distinct, or the identity
      // is being satisfied by a degenerate fixture rather than by the code.
      expect(new Set([parseMoney(f.Won), parseMoney(f.Lost), headline]).size).toBe(3);
    });
  }

  it("Open/at-stake sits OUTSIDE the identity, not inside it", async () => {
    render(<BetsTab leagueId="L1" owners={owners} />);
    const cards = within(await screen.findByTestId("bet-leader-cards"));
    const card = cards.getByText("Ann").closest("div.rounded-panel") as HTMLElement;
    const f = factMap(card);
    // Exposure on an unsettled bet is not money won or lost; folding it in
    // would break the headline.
    expect(parseMoney(f.Open)).toBe(20000);
    expect(parseMoney(f.Won) - parseMoney(f.Lost) - parseMoney(f.Open)).not.toBe(50000);
  });
});
