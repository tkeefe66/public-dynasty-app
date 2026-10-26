import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { DashboardClient } from "../components/DashboardClient";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), useSearchParams: () => new URLSearchParams() }));
vi.mock("../components/LeagueHeader", () => ({ LeagueHeader: () => null }));
vi.mock("../components/HeadlineMoves", () => ({ HeadlineMoves: () => null }));
vi.mock("../components/TradesTab", () => ({ TradesTab: () => null }));
vi.mock("../lib/api", () => ({
  dashboard: vi.fn().mockResolvedValue({
    league: { season: 2026, seasons: [2026, 2024] }, selected_year: 2024,
    selected_lens: "ktc", standings: [], total_trades: 0,
    unverified_season_owners: [{ user_id: "unknown", owner_name: "Alex", membership_status: "current" }],
  }),
  getProfiles: vi.fn().mockResolvedValue({}), getMe: vi.fn().mockResolvedValue({ sleeper_user_id: null }),
}));

it.each(["dashboard", "trades"] as const)("shows unverified participation on the %s surface", async (tab) => {
  // Mutation: the dashboard receives excluded owners but never renders the notice.
  render(<DashboardClient leagueId="sample" initialYear={2024} initialLens="ktc" initialTab={tab} />);
  expect(await screen.findByText("2024 participation unverified")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Alex" })).toHaveAttribute("href", "/league/sample/owner/unknown");
  expect(screen.getByText(/Not included in 2024 rankings/)).toBeInTheDocument();
});
