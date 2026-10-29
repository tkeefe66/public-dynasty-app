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
  it("hides provisional explanations for current and historical ratings", () => {
    for (const basis of ["current", "season_end"] as const) {
      const { container, unmount } = render(<RatingScopeNotice scope={{
        status: "provisional", basis, label: "Provisional career rating",
        as_of: "2025-01-07", current_valuation_note: "Estimated keeper picks",
        included_seasons: [2022, 2024], excluded_seasons: [{ season: 2023, reason: "Unresolved history" }],
        verified_owner_count: 9, excluded_rosters: [{ roster_id: 7, reason: "Unassigned" }],
        valuation_source: "stats_guy", prices_as_of: "2024-12-30", valuation_note: "Reconstructed placeholders",
      }} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });
  it("retains unavailable explanations and owner coverage", () => {
    render(<RatingScopeNotice scope={{
      status: "unavailable", basis: "current", label: "Rating unavailable",
      reason: "Future-pick prices are incomplete.", verified_owner_count: 9,
      excluded_rosters: [{ roster_id: 7, reason: "Current owner is unassigned." }],
    }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Future-pick prices are incomplete.");
    expect(screen.getByRole("status")).toHaveTextContent("Team 7: Current owner is unassigned.");
  });
  it("attributes an older archive to its actual valuation provider", () => {
    render(<RatingScopeNotice scope={{ status: "ready", basis: "season_end",
      label: "Franchise rating at end of 2021", valuation_source: "dynasty_process",
      prices_as_of: "2021-12-31" }} />);
    expect(screen.getByRole("link", { name: "DynastyProcess" })).toHaveAttribute("href", "https://dynastyprocess.com");
    expect(screen.queryByText("Stats Guy Fantasy")).not.toBeInTheDocument();
  });
  it("omits provisional banners at the standings call site", () => {
    render(<StandingsTable leagueId="L" rows={[]} year={2024} currentSeason={2026} ratingScope={{
      status: "provisional", basis: "season_end", label: "Provisional franchise rating at end of 2024",
      included_seasons: [2022, 2024], excluded_seasons: [{ season: 2023, reason: "Postseason results disagree." }],
    }} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/Provisional|Included seasons|Excluded seasons/)).not.toBeInTheDocument();
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
