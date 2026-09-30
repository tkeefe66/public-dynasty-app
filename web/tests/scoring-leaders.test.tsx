import { fireEvent, render, screen, within } from "@testing-library/react";
import { it, expect } from "vitest";
import { ScoringLeaders } from "@/components/ScoringLeaders";
import { TopBar } from "@/components/TopBar";
import { DashboardTabs } from "@/components/DashboardTabs";
import { ThemeProvider } from "@/components/ThemeProvider";

const data = {
  league_id: "123", league_name: "Test League", season: 2026, through_week: 3,
  updated_at: "2026-09-30T00:00:00Z",
  players: [
    { player_id: "a", name: "Alpha Receiver", position: "WR", team: "SEA", rank: 1, points: 60, games: 3, points_per_game: 20 },
    { player_id: "b", name: "Beta Receiver", position: "WR", team: "DEN", rank: 2, points: 40, games: 1, points_per_game: 40 },
    { player_id: "c", name: "Test Runner", position: "RB", team: "KC", rank: 1, points: 70, games: 3, points_per_game: 23.33 },
  ],
};

it("filters desktop and mobile together without changing positional ranks", () => {
  // Mutation: filter only one presentation, rerank search results, or sort by PPG.
  render(<ScoringLeaders data={data} />);
  expect(screen.getByText(/Season scoring through Week 3/)).toBeInTheDocument();
  for (const id of ["scoring-table", "scoring-cards"]) {
    const view = within(screen.getByTestId(id));
    expect(view.getByText("Alpha Receiver")).toBeInTheDocument();
    expect(view.queryByText("Test Runner")).not.toBeInTheDocument();
    expect(view.getAllByText(/Receiver/)[0]).toHaveTextContent("Alpha Receiver");
  }
  fireEvent.change(screen.getByRole("searchbox", { name: "Find a player" }), { target: { value: "Beta" } });
  expect(screen.getAllByText("WR2")).toHaveLength(2);
  expect(screen.queryByText("WR1")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "RB" }));
  expect(screen.getAllByText("Test Runner")).toHaveLength(2);
  expect(screen.queryByText("Alpha Receiver")).not.toBeInTheDocument();
});

it("names the first completed week as the prerequisite to scoring", () => {
  // Mutation: render a zero-point leaderboard or claim Week 0 results in preseason.
  render(<ScoringLeaders data={{ ...data, through_week: 0, players: [] }} />);
  expect(screen.getByText("Scoring starts after Week 1.")).toBeInTheDocument();
  expect(screen.queryByTestId("scoring-table")).not.toBeInTheDocument();
});

it("shows ties explicitly in both layouts", () => {
  // Mutation: display tied WR1 scores as unique first/second ranks.
  render(<ScoringLeaders data={{ ...data, players: data.players.slice(0, 2).map(p => ({ ...p, rank: 1, points: 60 })) }} />);
  expect(screen.getAllByText("WR1 · tied")).toHaveLength(4);
});

it("makes scoring reachable from both league navigation surfaces", () => {
  // Mutation: add the page without a mobile or desktop navigation destination.
  render(<ThemeProvider><TopBar leagueId="123" /><DashboardTabs leagueId="123" active="scoring" /></ThemeProvider>);
  const links = screen.getAllByRole("link", { name: "Scoring" });
  expect(links).toHaveLength(2);
  links.forEach(link => expect(link).toHaveAttribute("href", "/league/123/scoring"));
});
