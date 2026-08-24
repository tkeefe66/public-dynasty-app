import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ betsSummary: vi.fn() }));

import { betsSummary } from "@/lib/api";
import { SideBetsCard } from "@/components/ownerdeepdive/SideBetsCard";

const row = {
  owner: { user_id: "u_tom", owner_name: "Tom" },
  won: 3, lost: 1, pushed: 1,
  cents_won: 75000, cents_lost: 10000, net_cents: 65000,
  cents_at_stake: 5000, biggest_win_cents: 50000, worst_loss_cents: 10000,
};

describe("SideBetsCard", () => {
  // NB: async — a sync beforeEach here interacts with Vitest's unhandled-
  // rejection tracking and React's passive-effect flush timing to falsely
  // fail the "fetch rejects" case below, even though SideBetsCard's own
  // `.catch()` handles it (reproduced in isolation outside this component).
  beforeEach(async () => { vi.mocked(betsSummary).mockReset(); });

  it("renders the owner's record with signed net", async () => {
    vi.mocked(betsSummary).mockResolvedValue({ owners: [row] });
    render(<SideBetsCard leagueId="L1" userId="u_tom" />);
    expect(await screen.findByText("Side bets")).toBeInTheDocument();
    expect(screen.getByText("+$650")).toBeInTheDocument();
    expect(screen.getByText("3-1-1")).toBeInTheDocument();
    expect(screen.getByText("$500")).toBeInTheDocument(); // biggest win
  });

  it("renders nothing when the owner has no bet history", async () => {
    vi.mocked(betsSummary).mockResolvedValue({ owners: [] });
    const { container } = render(<SideBetsCard leagueId="L1" userId="u_tom" />);
    await waitFor(() => expect(betsSummary).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the summary fetch fails", async () => {
    vi.mocked(betsSummary).mockRejectedValue(new Error("boom"));
    const { container } = render(<SideBetsCard leagueId="L1" userId="u_tom" />);
    await waitFor(() => expect(betsSummary).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
