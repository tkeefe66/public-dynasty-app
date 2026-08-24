import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DashboardTabs } from "@/components/DashboardTabs";

/**
 * The phone's navigation.
 *
 * The invariant worth a test is the PAIRING: this bar and `TopBar`'s inline run
 * are the same destinations at two widths, and they must never both be on
 * screen. `TopBar.test.tsx` holds the other half (`hidden min-[701px]:flex`);
 * this holds `min-[701px]:hidden`. A change to one breakpoint without the other
 * produces either two navs or none, and both look plausible in a screenshot at
 * whichever width you happened to check.
 *
 * Draft-specific assertions (fifth cell, no icon, real route) live in
 * `draft-nav.test.tsx`; this file keeps the pairing invariant current.
 */
const TABS = ["Franchises", "Trades", "Owners", "Bets", "Draft"];

describe("DashboardTabs", () => {
  it("renders exactly the five destinations, in order", () => {
    render(<DashboardTabs leagueId="L1" active="dashboard" />);
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(TABS);
  });

  it("points each tab where TopBar's matching item points", () => {
    render(<DashboardTabs leagueId="L1" active="dashboard" />);
    const href = (name: string) =>
      screen.getByRole("link", { name: new RegExp(`^${name}$`, "i") }).getAttribute("href");
    expect(href("Franchises")).toBe("/league/L1");
    expect(href("Trades")).toBe("/league/L1?tab=trades");
    expect(href("Owners")).toBe("/league/L1?tab=owners");
    expect(href("Bets")).toBe("/league/L1?tab=bets");
    expect(href("Draft")).toBe("/league/L1/draft");
  });

  it("marks the active tab and only the active tab", () => {
    render(<DashboardTabs leagueId="L1" active="bets" />);
    const bets = screen.getByRole("link", { name: /^Bets$/i });
    expect(bets.getAttribute("aria-current")).toBe("page");
    expect(bets.className).toMatch(/font-bold/);
    expect(
      screen.getAllByRole("link").filter((l) => l.getAttribute("aria-current") === "page"),
    ).toHaveLength(1);
  });

  it("does not render above 701px, where TopBar's inline nav takes over", () => {
    const { container } = render(<DashboardTabs leagueId="L1" active="dashboard" />);
    expect(container.querySelector("nav")!.className).toMatch(/min-\[701px\]:hidden/);
  });

  it("is not fixed or sticky", () => {
    // `.design/readme.md`'s Layout rules — the reason this is a bar under the
    // masthead and not the bottom tab bar every phone app reaches for.
    const cls = render(<DashboardTabs leagueId="L1" active="dashboard" />)
      .container.querySelector("nav")!.className;
    expect(cls).not.toMatch(/\b(fixed|sticky)\b/);
  });

  it("gives every cell a 44px tap target", () => {
    const { container } = render(<DashboardTabs leagueId="L1" active="dashboard" />);
    for (const a of container.querySelectorAll("a")) {
      expect(a.className).toMatch(/min-h-tap/);
    }
  });
});
