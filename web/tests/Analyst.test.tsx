import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalystArchive } from "@/components/AnalystArchive";
import { HeadlineMoves } from "@/components/HeadlineMoves";
import type { DashboardResp } from "@/lib/types";

const editions = [
  { season: 2026, week: 2, league_name: "Test League", generated_at: "2026-09-22T12:00:00Z", markdown: "## Heroes\n**Alice** won again.", model: "test" },
  { season: 2026, week: 1, league_name: "Test League", generated_at: "2026-09-15T12:00:00Z", markdown: "## Opening week\nBob wins.", model: "test" },
];

describe("The Analyst", () => {
  it("labels a correction and preserves readable original text", () => {
    // Mutation: silently replace the article without exposing the original.
    render(<AnalystArchive leagueId="123" editions={[{
      ...editions[0], revision: 2, correction_note: "Corrected ownership.", original_markdown: "Original draft.",
    }]} />);
    expect(screen.getByText("Corrected ownership.")).toBeInTheDocument();
    expect(screen.getByText("View original edition (contains corrected errors)")).toBeInTheDocument();
    expect(screen.getByText("Original draft.")).toBeInTheDocument();
  });
  it("links the homepage recap to its own league archive", () => {
    // Mutation: omit the link or send it to another league.
    render(<HeadlineMoves data={{ phase: "regular", phase_week: 1 } as DashboardResp} leagueId="123" />);
    expect(screen.getByRole("link", { name: /Read The Analyst/ })).toHaveAttribute("href", "/league/123/analyst");
  });
  it("opens a saved edition and provides permanent week links", () => {
    // Mutation: ignore the selected edition and always render newest.
    render(<AnalystArchive leagueId="123" editions={editions} selected="2026-1" />);
    expect(screen.getByRole("heading", { name: "Opening week" })).toBeInTheDocument();
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "2026 · Week 2" })).toHaveAttribute("href", "/league/123/analyst?edition=2026-2");
  });
  it("shows a waiting state before the first saved edition", () => {
    // Mutation: present invented recap content when the archive is empty.
    render(<AnalystArchive leagueId="123" editions={[]} />);
    expect(screen.getByText("The first edition is on its way.")).toBeInTheDocument();
  });
  it("does not execute markup in generated text", () => {
    // Mutation: render untrusted model output as raw HTML.
    const { container } = render(<AnalystArchive leagueId="123" editions={[{ ...editions[0], markdown: '<script>alert(1)</script>\n\n## Heroes\n**Alice** wins.' }]} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("strong")?.textContent).toBe("Alice");
  });
});
