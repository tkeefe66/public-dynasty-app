import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OwnerLabel } from "../components/OwnerLabel";

describe("OwnerLabel", () => {
  // The Sleeper team name renders in exactly one place — the dashboard
  // ledgers' Franchise column (StandingsTable). OwnerLabel's subject is always
  // the person, so it is owner-name-only in every variant.
  it("never shows the team name, even when the owner carries one", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "mike_t", team_name: "Dynasty Warriors" }} />);
    expect(screen.getByText("mike_t")).toBeInTheDocument();
    expect(screen.queryByText("Dynasty Warriors")).not.toBeInTheDocument();
  });

  it("shows the owner name when team_name is absent", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "mike_t" }} />);
    expect(screen.getByText("mike_t")).toBeInTheDocument();
  });

  it("renders an initial monogram when there is no avatar_url", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "carol" }} />);
    expect(screen.getByText("C")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders the avatar image when avatar_url is set", () => {
    const { container } = render(<OwnerLabel owner={{ user_id: "u1", owner_name: "alice", avatar_url: "https://x/y.png" }} />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "https://x/y.png");
  });

  it("renders square avatars, never rounded-full — a circle would be the only radius in the system", () => {
    const { container: withPhoto } = render(
      <OwnerLabel owner={{ user_id: "u1", owner_name: "alice", avatar_url: "https://x/y.png" }} />,
    );
    expect(withPhoto.querySelector("img")?.className).not.toMatch(/rounded/);
    const { container: withFallback } = render(<OwnerLabel owner={{ user_id: "u1", owner_name: "carol" }} />);
    expect(withFallback.querySelector("span.bg-rule")?.className).not.toMatch(/rounded/);
  });

  it("renders the fallback initial at 26px (one rule tall) in Geist Mono on a --rule fill", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "carol" }} />);
    const fallback = screen.getByText("C");
    expect(fallback.className).toMatch(/h-\[26px\]/);
    expect(fallback.className).toMatch(/w-\[26px\]/);
    expect(fallback.className).toMatch(/font-mono/);
    expect(fallback.className).toMatch(/bg-rule/);
  });

  it("compact variant never shows the team line", () => {
    render(<OwnerLabel owner={{ user_id: "u1", owner_name: "mike_t", team_name: "Dynasty Warriors" }} variant="compact" />);
    expect(screen.getByText("mike_t")).toBeInTheDocument();
    expect(screen.queryByText("Dynasty Warriors")).not.toBeInTheDocument();
  });
});
