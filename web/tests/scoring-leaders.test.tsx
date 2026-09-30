import { fireEvent, render, screen, within } from "@testing-library/react";
import { it, expect } from "vitest";
import { ScoringLeaders } from "@/components/ScoringLeaders";
import { TopBar } from "@/components/TopBar";
import { DashboardTabs } from "@/components/DashboardTabs";
import { ThemeProvider } from "@/components/ThemeProvider";
import type { ScoringResp } from "@/lib/scoring";

const players = [
  { player_id: "a", name: "Alpha Receiver", position: "WR", team: "SEA", rank: 1, points: 60, games: 3, points_per_game: 20 },
  { player_id: "b", name: "Beta Receiver", position: "WR", team: "DEN", rank: 2, points: 40, games: 1, points_per_game: 40 },
  { player_id: "c", name: "Test Runner", position: "RB", team: "KC", rank: 1, points: 70, games: 3, points_per_game: 23.33 },
  ...[3, 4, 5, 6].map(rank => ({ player_id: `wr${rank}`, name: `Receiver ${rank}`, position: "WR", team: "SEA", rank, points: 10 - rank, games: 2, points_per_game: (10 - rank) / 2 })),
];
const data: ScoringResp = {
  league_id: "123", league_name: "Test League", season: 2026, through_week: 3,
  updated_at: "2026-09-30T00:00:00Z", players,
  franchises: [
    { roster_id: 1, owner_id: "owner", name: "First Team", owner_name: "Manager", players: [
      ...players.filter(p => p.player_id !== "a"),
      { player_id: "inactive", name: "Inactive Player", position: "WR", team: null, rank: null, points: null, games: 0, points_per_game: null },
    ] },
    { roster_id: 2, owner_id: null, name: "Franchise 2", owner_name: null, players: [] },
  ],
};

it("opens a position board with five leaders per card and expands the complete rankings", () => {
  // Mutation: default to WR only, rank by PPG, or leave lower-ranked players inaccessible.
  render(<ScoringLeaders data={data} />);
  expect(screen.getByText(/Through Week 3/)).toBeInTheDocument();
  const receivers = within(screen.getByRole("region", { name: "Wide receivers" }));
  expect(receivers.getAllByRole("listitem")[0]).toHaveTextContent("Alpha Receiver");
  expect(receivers.getByText("Free agent")).toBeInTheDocument();
  expect(receivers.queryByText("Receiver 6")).not.toBeInTheDocument();
  expect(screen.getByText("Test Runner")).toBeInTheDocument();
  fireEvent.click(receivers.getByRole("button", { name: "Explore WR rankings" }));
  expect(receivers.getByText("Receiver 6")).toBeInTheDocument();
  expect(receivers.getByRole("button", { name: "Show top five" })).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(receivers.getByRole("button", { name: "Show top five" }));
  expect(receivers.queryByText("Receiver 6")).not.toBeInTheDocument();
});

it("filters both views and franchises without reranking search results", () => {
  // Mutation: rerank a team's best WR as WR1, ignore franchise filters, or lose filters on switching views.
  render(<ScoringLeaders data={data} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Franchise" }), { target: { value: "1" } });
  expect(screen.queryByText("Alpha Receiver")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "WR" }));
  expect(screen.queryByText("Test Runner")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Find a player" }), { target: { value: "beta" } });
  expect(screen.getByText("WR2")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Franchises" }));
  expect(screen.getByText("WR2")).toBeInTheDocument();
  expect(screen.getByText("Beta Receiver")).toBeInTheDocument();
  expect(screen.queryByText("Test Runner")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Franchise 2" })).not.toBeInTheDocument();
});

it("shows complete current rosters, unowned franchises, and unranked players without inventing scores", () => {
  // Mutation: omit unowned teams/inactive players or display their unknown score as zero.
  render(<ScoringLeaders data={data} />);
  fireEvent.click(screen.getByRole("button", { name: "Franchises" }));
  const first = within(screen.getByRole("region", { name: "First Team" }));
  expect(first.getByText(/Manager · 7 players/)).toBeInTheDocument();
  fireEvent.click(first.getByRole("button", { name: "View all 7 players" }));
  const inactive = first.getByText("Inactive Player").closest("li")!;
  expect(inactive).toHaveTextContent("No games recorded");
  expect(inactive).not.toHaveTextContent("0.00");
  expect(screen.getByRole("region", { name: "Franchise 2" })).toHaveTextContent("No players on this roster.");
});

it("keeps ties explicit after filtering and distinguishes zero and negative scores from unknown", () => {
  // Mutation: compute ties from the filtered team or use truthiness to hide a real zero score.
  const tied = players.slice(0, 2).map(p => ({ ...p, rank: 1, points: 0, points_per_game: 0 }));
  render(<ScoringLeaders data={{ ...data, players: tied, franchises: [{ ...data.franchises[0], players: [tied[1], { ...players[3], points: -2, points_per_game: -1 }] }] }} />);
  fireEvent.click(screen.getByRole("button", { name: "Franchises" }));
  expect(screen.getByText("WR1 · tied")).toBeInTheDocument();
  expect(screen.getByText("0.00")).toBeInTheDocument();
  expect(screen.getByText("-2.00")).toBeInTheDocument();
});

it("explains an empty search and keeps preseason rosters available", () => {
  // Mutation: render a blank board or make current rosters inaccessible before Week 1.
  const { rerender } = render(<ScoringLeaders data={data} />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "nobodymatches" } });
  expect(screen.getByText("No players match these filters.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByText("Alpha Receiver")).toBeInTheDocument();
  rerender(<ScoringLeaders data={{ ...data, through_week: 0, players: [] }} />);
  expect(screen.getByText("Scoring starts after Week 1.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Franchises" }));
  expect(screen.getByRole("region", { name: "First Team" })).toBeInTheDocument();
});

it("keeps server tie metadata for roster positions absent from the Positions board", () => {
  // Mutation: infer ties solely from currently eligible position leaders.
  render(<ScoringLeaders data={{ ...data, franchises: [{ ...data.franchises[0], players: [{ ...players[0], position: "K", tied: true }] }] }} />);
  fireEvent.click(screen.getByRole("button", { name: "Franchises" }));
  expect(screen.getByText("K1 · tied")).toBeInTheDocument();
});

it("makes scoring reachable from both league navigation surfaces", () => {
  // Mutation: add the page without a mobile or desktop navigation destination.
  render(<ThemeProvider><TopBar leagueId="123" /><DashboardTabs leagueId="123" active="scoring" /></ThemeProvider>);
  const links = screen.getAllByRole("link", { name: "Scoring" });
  expect(links).toHaveLength(2);
  links.forEach(link => expect(link).toHaveAttribute("href", "/league/123/scoring"));
});
