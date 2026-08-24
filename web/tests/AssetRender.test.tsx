import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { AssetRender } from "@/components/AssetRender";

describe("AssetRender", () => {
  it("renders a plain player by name", () => {
    const { container } = render(
      <AssetRender asset={{ name: "Oronde Gadsden", player_id: "1" }} displayNames={{}} />,
    );
    expect(container.textContent).toContain("Oronde Gadsden");
  });

  it("renders an undrafted pick as just the pick (no 'became')", () => {
    const { container } = render(
      <AssetRender asset={{ season: 2027, round: 2 }} displayNames={{}} />,
    );
    expect(container.textContent).toContain("2027 2nd pick");
    expect(container.textContent).not.toContain("became");
  });

  it("annotates a flipped pick with the player it became (ownership not implied)", () => {
    const { container } = render(
      <AssetRender
        asset={{ season: 2026, round: 1, drafted_player_name: "Makai Lemon" }}
        displayNames={{}}
      />,
    );
    // Still shown as a pick (this owner flipped it)...
    expect(container.textContent).toContain("2026 1st pick");
    // ...annotated with what it became.
    expect(container.textContent).toContain("became Makai Lemon");
  });

  it("renders a kept pick (via_pick) as the player the owner drafted", () => {
    const { container } = render(
      <AssetRender
        asset={{ name: "Makai Lemon", via_pick: { season: 2026, round: 1 } }}
        displayNames={{}}
      />,
    );
    expect(container.textContent).toContain("2026 1st pick");
    expect(container.textContent).toContain("Makai Lemon");
    expect(container.textContent).not.toContain("became");
  });
});
