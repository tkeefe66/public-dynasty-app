import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LeagueNotes } from "../components/LeagueNotes";

const REDRAFT_NOTE =
  "Redraft values cover roughly the top 200 players; deep bench and IDP " +
  "players are unvalued, and traded draft picks are unvalued (priced at 0)";

describe("LeagueNotes", () => {
  it("renders every backend warning verbatim under a Coverage heading", () => {
    render(<LeagueNotes notes={[REDRAFT_NOTE, "Second note"]} />);
    expect(screen.getByText(REDRAFT_NOTE)).toBeInTheDocument();
    expect(screen.getByText("Second note")).toBeInTheDocument();
    expect(screen.getByText("Coverage")).toBeInTheDocument();
  });

  it("renders nothing at all when there are no warnings", () => {
    // Absence, not an empty state: no heading, no placeholder, no section.
    const { container } = render(<LeagueNotes notes={[]} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("Coverage")).toBeNull();
  });

  it("renders nothing when the field is missing entirely (older cached response)", () => {
    const { container } = render(<LeagueNotes notes={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
