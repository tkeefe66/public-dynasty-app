import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError, scoringLeaders } from "@/lib/api";
import ScoringPage from "@/app/league/[id]/scoring/page";

vi.mock("@/lib/api", () => ({
  ApiError: class extends Error { constructor(public status: number, message: string) { super(message); } },
  scoringLeaders: vi.fn(),
}));
vi.mock("@/components/Shell", () => ({ Shell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/components/DashboardTabs", () => ({ DashboardTabs: () => null }));

describe("scoring failure actions", () => {
  it.each([403, 404, 422])("does not offer retry for permanent HTTP %s", async (status) => {
    // Mutation: expose Try again for unsupported league/platform inputs.
    vi.mocked(scoringLeaders).mockRejectedValue(new ApiError(status, "Scoring unavailable"));
    render(await ScoringPage({ params: { id: "999.l.123" } }));
    expect(screen.queryByRole("link", { name: "Try again" })).toBeNull();
  });
  it("links a Yahoo connection failure to reconnect", async () => {
    // Mutation: retry the same request instead of offering required account repair.
    vi.mocked(scoringLeaders).mockRejectedValue(new ApiError(409, "Reconnect Yahoo"));
    render(await ScoringPage({ params: { id: "999.l.123" } }));
    expect(screen.getByRole("link", { name: "Reconnect Yahoo" })).toHaveAttribute("href", "/leagues/add");
  });
  it("offers retry for a temporary upstream failure", async () => {
    // Mutation: suppress recovery for transient provider failures.
    vi.mocked(scoringLeaders).mockRejectedValue(new ApiError(503, "Yahoo timed out"));
    render(await ScoringPage({ params: { id: "999.l.123" } }));
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute("href", "/league/999.l.123/scoring");
  });
});
