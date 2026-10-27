import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RatingScopeNotice } from "../components/RatingScopeNotice";
import { StandingsTable } from "../components/StandingsTable";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const missing = { status: "unavailable" as const, basis: "season_end" as const,
  label: "Historical data unavailable", reason: "Verified historical asset prices are missing." };

describe("rating scope", () => {
  it("attributes an older archive to its actual valuation provider", () => {
    render(<RatingScopeNotice scope={{ status: "ready", basis: "season_end",
      label: "Franchise rating at end of 2021", valuation_source: "dynasty_process",
      prices_as_of: "2021-12-31" }} />);
    expect(screen.getByRole("link", { name: "DynastyProcess" })).toHaveAttribute("href", "https://dynastyprocess.com");
    expect(screen.queryByText("Stats Guy Fantasy")).not.toBeInTheDocument();
  });
  it("discloses provisional coverage and excluded reasons at the standings call site", () => {
    // Mutation: suppress coverage disclosure for provisional ratings.
    render(<StandingsTable leagueId="L" rows={[]} year={2024} currentSeason={2026} ratingScope={{
      status: "provisional", basis: "season_end", label: "Franchise rating at end of 2024",
      included_seasons: [2022, 2024], excluded_seasons: [
        { season: 2021, reason: "Final standings are unresolved." },
        { season: 2023, reason: "Postseason results disagree." },
      ],
    }} />);
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Provisional");
    expect(notice).toHaveTextContent("Included seasons: 2022, 2024");
    expect(notice).toHaveTextContent("2021: Final standings are unresolved.");
    expect(notice).toHaveTextContent("2023: Postseason results disagree.");
    expect(notice).toHaveTextContent("Incomplete history");
    expect(notice).toHaveTextContent("Do not compare directly with ratings based on complete history");
  });

  it("retains the cutoff and historical pricing attribution for provisional ratings", () => {
    // Mutation: limit cutoff and valuation attribution to ready ratings.
    render(<RatingScopeNotice scope={{ status: "provisional", basis: "season_end",
      label: "Provisional franchise rating at end of 2024", as_of: "2025-01-07",
      valuation_source: "stats_guy", prices_as_of: "2024-12-30",
      valuation_note: "Unranked players use a zero replacement floor." }} />);
    expect(screen.getByRole("status")).toHaveTextContent("As of 2025-01-07");
    expect(screen.getByRole("link", { name: "Stats Guy Fantasy" })).toHaveAttribute("href", "https://statsguyfantasy.com");
    expect(screen.getByRole("status")).toHaveTextContent("2024-12-30");
    expect(screen.getByRole("status")).toHaveTextContent("zero replacement floor");
  });

  it("attributes historical estimates and discloses missing-player policy", () => {
    render(<RatingScopeNotice scope={{ status: "ready", basis: "season_end",
      label: "Franchise rating at end of 2025", valuation_source: "stats_guy",
      prices_as_of: "2025-12-30", valuation_note: "Unranked players use a zero replacement floor." }} />);
    expect(screen.getByRole("link", { name: "Stats Guy Fantasy" })).toHaveAttribute("href", "https://statsguyfantasy.com");
    expect(screen.getByRole("status")).toHaveTextContent("2025-12-30");
    expect(screen.getByRole("status")).toHaveTextContent("zero replacement floor");
  });
  it("explains missing historical evidence next to the franchise table", () => {
    // Mutation: omit the scope notice at the actual standings call site.
    render(<StandingsTable leagueId="L" rows={[]} year={2024} currentSeason={2026} ratingScope={missing} />);
    expect(screen.getByText("Historical data unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Verified historical asset prices are missing/)).toBeInTheDocument();
  });

  it("keeps January dates attached to the selected fantasy season", () => {
    // Mutation: derive the season label from the cutoff's calendar year.
    render(<RatingScopeNotice scope={{ status: "ready", basis: "season_end",
      label: "Franchise rating at end of 2024", as_of: "2025-01-07" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Franchise rating at end of 2024 · As of 2025-01-07");
  });
});
