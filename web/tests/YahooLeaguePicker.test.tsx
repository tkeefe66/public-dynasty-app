import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { YahooLeaguePicker } from "@/components/YahooLeaguePicker";
import { addLeague, yahooLeagues, yahooStatus } from "@/lib/api";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({
  yahooStatus: vi.fn(), yahooLeagues: vi.fn(), addLeague: vi.fn(), disconnectYahoo: vi.fn(),
}));
beforeEach(() => vi.clearAllMocks());

it("offers read-only connection when disconnected", async () => {
  // Mutation: show only the Sleeper input or hide Yahoo behind configuration.
  vi.mocked(yahooStatus).mockResolvedValue({ configured: true, status: "disconnected" });
  render(<YahooLeaguePicker />);
  expect(await screen.findByRole("button", { name: "Connect Yahoo" })).toBeEnabled();
  expect(screen.getByText(/read-only/i)).toBeInTheDocument();
});

it("adds discovered league then opens it; imported leagues have Open links", async () => {
  // Mutation: Add navigates without saving membership, or posts a different key.
  vi.mocked(yahooStatus).mockResolvedValue({ configured: true, status: "connected" });
  vi.mocked(yahooLeagues).mockResolvedValue([
    { league_id: "999.l.123", name: "Example Keepers", season: 2026, total_rosters: 10, format: "keeper", already_imported: false },
    { league_id: "999.l.456", name: "Imported", season: 2026, total_rosters: 12, format: "redraft", already_imported: true },
  ]);
  vi.mocked(addLeague).mockResolvedValue({ league_id: "999.l.123" } as never);
  render(<YahooLeaguePicker />);
  fireEvent.click(await screen.findByRole("button", { name: "Add Example Keepers" }));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/league/999.l.123"));
  expect(addLeague).toHaveBeenCalledWith("999.l.123", { name: "Example Keepers" });
  expect(screen.getByRole("link", { name: "Open Imported" })).toHaveAttribute("href", "/league/999.l.456");
});

it("keeps connection errors visible and offers reconnect", async () => {
  // Mutation: swallow a revoked authorization and display an empty league list.
  vi.mocked(yahooStatus).mockResolvedValue({ configured: true, status: "connected" });
  vi.mocked(yahooLeagues).mockRejectedValue(new Error("Yahoo refused access. Reconnect Yahoo."));
  render(<YahooLeaguePicker />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Yahoo refused access");
  expect(screen.getByRole("button", { name: "Reconnect Yahoo" })).toBeEnabled();
});
