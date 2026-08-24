import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TopBar } from "@/components/TopBar";
import { DashboardTabs } from "@/components/DashboardTabs";

// LeagueSwitcher fetches its league list on mount; these tests don't care what
// it lists, so it stands in as an inert marker (same approach as TopBar.test.tsx).
vi.mock("@/components/LeagueSwitcher", () => ({
  LeagueSwitcher: () => <span data-testid="league-switcher" />,
}));
vi.mock("@/components/WeekNote", () => ({ WeekNote: () => null }));
vi.mock("@/components/ThemeToggle", () => ({
  ThemeToggle: () => <span data-testid="theme-toggle" />,
}));

/**
 * Task 4: Draft in both navs. Both `TopBar`'s inline run and `DashboardTabs`'
 * phone bar gained a fifth destination, `/league/{id}/draft` — a real route,
 * not a `?tab=` on the league root, and drawn with no icon since nothing in
 * the nineteen marks reads as "draft" (Bets already sets that precedent).
 */
describe("Draft in both navs", () => {
  it("TopBar renders a Draft link pointing at /league/{id}/draft", () => {
    render(<TopBar leagueId="L1" activeNav="dashboard" />);
    const draft = screen.getByRole("link", { name: /^Draft$/i });
    expect(draft.getAttribute("href")).toBe("/league/L1/draft");
  });

  it("DashboardTabs renders five cells, the fifth being Draft", () => {
    render(<DashboardTabs leagueId="L1" active="dashboard" />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(5);
    expect(links[4].textContent).toBe("Draft");
    expect(links[4].getAttribute("href")).toBe("/league/L1/draft");
  });

  it("renders the Draft nav item with no icon/mark, like Bets", () => {
    render(<TopBar leagueId="L1" activeNav="dashboard" />);
    const draft = screen.getByRole("link", { name: /^Draft$/i });
    const bets = screen.getByRole("link", { name: /^Bets$/i });
    expect(draft.querySelector("svg")).toBeNull();
    expect(bets.querySelector("svg")).toBeNull();
  });
});
