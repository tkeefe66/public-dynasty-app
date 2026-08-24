import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeCard } from "@/components/TradeCard";
import type { LatestTrade } from "@/lib/types";

const TRADE: LatestTrade = {
  trade_id: "t1",
  date: "2026-08-07",
  week: 1,
  parties: [
    { user_id: "u1", owner_name: "Smitty", avatar_url: null, team_name: null },
    { user_id: "u2", owner_name: "Cormac", avatar_url: null, team_name: null },
  ],
  assets_short: "Stefon Diggs ↔ 2027 2nd",
  swing_ktc: 619,
  swing_prod: 0,
} as unknown as LatestTrade;

/**
 * The bug this file exists for: a rule marked desktop-only rendered anyway and
 * the phone showed both variants stacked, because `display` was being set from
 * two places at equal specificity and `hidden` lost.
 *
 * The mechanism MOVED at the Furniture port but did not go away. It used to be
 * `.ruled > *` in globals.css winning over `@tailwind utilities`; now `Row`
 * carries `grid` as a utility of its own, so a `hidden` on the same element is
 * a plain utility-vs-utility conflict decided by Tailwind's internal ordering
 * — still not something to leave to luck. The invariant is unchanged: a fixed
 * number of rows, and no breakpoint class on any of them. Vary the CONTENTS of
 * a row responsively, never whether the row exists.
 *
 * jsdom does no layout, so this cannot assert pixels — e2e/viewport.spec.ts
 * owns that. What it can assert is the structure that makes the pixel bug
 * impossible.
 */
describe("TradeCard", () => {
  function entry() {
    const { container } = render(<TradeCard leagueId="123" trade={TRADE} />);
    const link = container.querySelector("a");
    if (!link) throw new Error("entry root not found");
    return link;
  }

  it("renders exactly two rules, the same at every width", () => {
    expect(entry().children).toHaveLength(2);
  });

  it("puts no responsive or hidden class on any row of the entry", () => {
    // These would be silently ignored by the cascade — the rule renders anyway.
    for (const rule of Array.from(entry().children)) {
      const cls = rule.className.toString();
      expect(cls, `rule carries a breakpoint/hidden class: "${cls}"`).not.toMatch(
        /(^|\s)hidden(\s|$)|min-\[\d+px\]:/,
      );
    }
  });

  it("shows each owner exactly once", () => {
    render(<TradeCard leagueId="123" trade={TRADE} />);
    // Would be 2 if both a desktop and a phone variant rendered.
    expect(screen.getAllByText("Smitty")).toHaveLength(1);
    expect(screen.getAllByText("Cormac")).toHaveLength(1);
  });

  it("keeps the haul and the value on the phone", () => {
    render(<TradeCard leagueId="123" trade={TRADE} />);
    expect(screen.getByText("Stefon Diggs ↔ 2027 2nd")).toBeInTheDocument();
    expect(screen.getByText("+619")).toBeInTheDocument();
  });
});
