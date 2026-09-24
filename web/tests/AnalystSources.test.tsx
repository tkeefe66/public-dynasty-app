import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalystArchive } from "@/components/AnalystArchive";
import { AnalystSources } from "@/components/AnalystSources";

const sources = [{ publisher: "RotoBaller", title: "Quarterback exits early", published_at: "2026-09-22T02:00:00Z",
  url: "https://www.rotoballer.com/player-news/example/1" }];

describe("Analyst evidence sources", () => {
  it("renders saved source attribution and missing-coverage note below the article", () => {
    // Mutation: collect sources but omit them from the actual archive page.
    render(<AnalystArchive leagueId="test" editions={[{
      season: 2026, week: 2, league_name: "Test", generated_at: "2026-09-23T12:00:00Z", model: "test",
      markdown: "An injury shortened the outing.", sources, context_note: "Some snap counts were unavailable.",
    }]} />);
    expect(screen.getByRole("link", { name: "Quarterback exits early" })).toHaveAttribute("href", sources[0].url);
    expect(screen.getByText(/RotoBaller/)).toBeInTheDocument();
    expect(screen.getByText("Some snap counts were unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Quarterback exits early" })).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows publisher-only entries and refuses unsafe or unrelated source URLs", () => {
    // Mutation: make arbitrary stored URLs clickable, including deceptive subdomains.
    render(<AnalystSources sources={[
      { ...sources[0], title: "No original URL", url: null },
      { ...sources[0], title: "Unsafe", url: "javascript:alert(1)" },
      { ...sources[0], title: "Impersonated", url: "https://rotoballer.com.evil.example/" },
      { ...sources[0], title: "Credentialed", url: "https://user:pass@rotoballer.com/" },
    ]} />);
    expect(screen.getByText("No original URL")).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("keeps old editions free of an invented evidence section", () => {
    // Mutation: render a claim of sourced reporting when no sources were saved.
    const { container } = render(<AnalystSources />);
    expect(container).toBeEmptyDOMElement();
  });
});
