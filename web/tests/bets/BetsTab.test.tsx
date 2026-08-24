import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  listBets: vi.fn(),
  betsSummary: vi.fn(),
  createBet: vi.fn(),
  updateBet: vi.fn(),
}));

import { betsSummary, createBet, listBets, updateBet } from "@/lib/api";
import { BetsTab } from "@/components/bets/BetsTab";
import type { StandingRow } from "@/lib/types";

const owners = [
  { user_id: "u_tom", owner: { user_id: "u_tom", owner_name: "Tom" } },
  { user_id: "u_mike", owner: { user_id: "u_mike", owner_name: "Mike" } },
] as unknown as StandingRow[];

const ref = (uid: string, name: string) => ({ user_id: uid, owner_name: name });

const settledBet = {
  id: "b1",
  season: 2026,
  description: "Tom finishes above Mike",
  amount_cents: 50000,
  side_a: ref("u_tom", "Tom"),
  side_b: ref("u_mike", "Mike"),
  status: "settled" as const,
  winner_owner_id: "u_tom",
  made_at: "2026-07-01",
  settled_at: "2026-07-10",
};

const openBet = {
  ...settledBet,
  id: "b2",
  description: "Mike wins the toilet bowl",
  status: "open" as const,
  winner_owner_id: null,
  settled_at: null,
  amount_cents: 2000,
};

const summary = {
  owners: [
    {
      owner: ref("u_tom", "Tom"),
      won: 1, lost: 0, pushed: 0,
      cents_won: 50000, cents_lost: 0, net_cents: 50000,
      cents_at_stake: 2000, biggest_win_cents: 50000, worst_loss_cents: 0,
    },
    {
      owner: ref("u_mike", "Mike"),
      won: 0, lost: 1, pushed: 0,
      cents_won: 0, cents_lost: 50000, net_cents: -50000,
      cents_at_stake: 2000, biggest_win_cents: 0, worst_loss_cents: 50000,
    },
  ],
};

beforeEach(() => {
  vi.mocked(listBets).mockResolvedValue({ bets: [settledBet, openBet] });
  vi.mocked(betsSummary).mockResolvedValue(summary);
  vi.mocked(updateBet).mockResolvedValue(settledBet);
});

/** The text of a `Meta` fact — label and value live in separate nodes. */
const facts = (scope: HTMLElement) =>
  Array.from(scope.querySelectorAll("span.whitespace-nowrap")).map((n) =>
    n.textContent?.replace(/\s+/g, " ").trim(),
  );

describe("BetsTab", () => {
  it("renders the leaderboard with signed nets and the ledger", async () => {
    render(<BetsTab leagueId="L1" owners={owners} />);
    // Both the leaderboard and the ledger render a desktop variant and a phone
    // variant (one visible per breakpoint), so every figure and every bet
    // description legitimately appears twice — same convention as
    // StandingsTable.test.tsx.
    expect((await screen.findAllByText("+$500")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("−$500").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Tom finishes above Mike").length).toBe(2);
  });

  describe("phone layout", () => {
    it("gives each owner a card: name, NET headline, and money facts", async () => {
      render(<BetsTab leagueId="L1" owners={owners} />);
      const cards = within(await screen.findByTestId("bet-leader-cards"));

      // The headline is NET — signed, toned, under a "Net" label.
      const net = cards.getByText("+$500");
      expect(net.className).toContain("text-pos");
      expect(cards.getByText("−$500").className).toContain("text-neg");
      expect(cards.getAllByText("Net").length).toBe(2);

      // The facts reconcile with the headline: net = won − lost. "At stake"
      // reads as "Open" on a card, and the record is kept as a fact rather
      // than dropped, so no desktop column is lost on a phone.
      const tomCard = cards.getByText("Tom").closest("div.rounded-panel")!;
      expect(facts(tomCard as HTMLElement)).toEqual([
        "Won $500",
        "Lost $0",
        "Open $20",
      ]);
    });

    it("dims a zero money fact instead of leaving it full-weight ink", async () => {
      render(<BetsTab leagueId="L1" owners={owners} />);
      const cards = within(await screen.findByTestId("bet-leader-cards"));
      // Tom lost nothing. A zero is `--dim`, never untoned (untoned renders as
      // ink and reads as a result), and never `--pos`/`--neg` (no sign).
      const zero = cards.getAllByText("$0")[0];
      expect(zero.className).toContain("text-dim");
      expect(zero.className).not.toMatch(/text-(pos|neg)/);
    });

    it("gives each bet a card led by its own description, stake as headline", async () => {
      render(<BetsTab leagueId="L1" owners={owners} />);
      const cards = within(await screen.findByTestId("bet-cards"));

      // The description IS the card's name — it is the subject of the entry.
      expect(cards.getByText("Tom finishes above Mike").className).toContain(
        "font-display",
      );
      // The stake is the headline figure, under an "At stake" label.
      expect(cards.getByText("$500")).toBeInTheDocument();
      expect(cards.getByText("$20")).toBeInTheDocument();
      expect(cards.getAllByText("At stake").length).toBe(2);
    });

    it('reads a settled bet as "Won by <name>" in PLAIN INK, never green', async () => {
      render(<BetsTab leagueId="L1" owners={owners} />);
      const cards = within(await screen.findByTestId("bet-cards"));

      const settled = cards
        .getByText("Tom finishes above Mike")
        .closest("div.rounded-panel")! as HTMLElement;
      expect(facts(settled)).toEqual([
        "Tom vs Mike", "Season 2026", "Made Jul 1, 2026", "Won by Tom",
      ]);

      // A name is not a signed value, so it takes no tone. Colour may only
      // carry what the figure or the sort order already carries.
      const wonBy = within(settled).getByText(/won by/i);
      const value = wonBy.querySelector("b")!;
      expect(value.textContent).toBe("Tom");
      expect(value.className).not.toMatch(/text-(pos|neg)/);
    });

    it("reads an open bet as Status Open", async () => {
      render(<BetsTab leagueId="L1" owners={owners} />);
      const cards = within(await screen.findByTestId("bet-cards"));
      const open = cards
        .getByText("Mike wins the toilet bowl")
        .closest("div.rounded-panel")! as HTMLElement;
      expect(facts(open)).toEqual([
        "Tom vs Mike", "Season 2026", "Made Jul 1, 2026", "Status Open",
      ]);
    });

    it("keeps every ledger action on the card, at a 44px tap target", async () => {
      render(<BetsTab leagueId="L1" owners={owners} />);
      const cards = within(await screen.findByTestId("bet-cards"));

      // The open bet carries all four actions; the settled one carries Reopen.
      const action = cards.getByRole("button", { name: "Mike won" });
      expect(action.className).toContain("min-h-tap");
      expect(cards.getByRole("button", { name: "Reopen" })).toBeInTheDocument();

      fireEvent.click(action);
      await waitFor(() =>
        expect(updateBet).toHaveBeenCalledWith("L1", "b2", {
          status: "settled",
          winner_owner_id: "u_mike",
        }),
      );
    });
  });

  it("keeps the record form behind the button until it is pressed", async () => {
    render(<BetsTab leagueId="L1" owners={owners} />);
    await screen.findAllByText("+$500");

    // Five fields sitting open push the ledger below the fold on a phone, so
    // the form is gated at every width and the trigger is a 44px target.
    expect(screen.queryByLabelText("Side A")).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "Record a bet" });
    expect(trigger.className).toContain("min-h-tap");

    fireEvent.click(trigger);
    expect(screen.getByLabelText("Side A")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByLabelText("Side A")).not.toBeInTheDocument();
  });

  it("settles an open bet via the winner action", async () => {
    render(<BetsTab leagueId="L1" owners={owners} />);
    await screen.findAllByText("+$500");
    fireEvent.click(screen.getAllByRole("button", { name: "Tom won" })[0]);
    await waitFor(() =>
      expect(updateBet).toHaveBeenCalledWith("L1", "b2", {
        status: "settled",
        winner_owner_id: "u_tom",
      }),
    );
  });

  it("shows the empty state when there are no bets", async () => {
    vi.mocked(listBets).mockResolvedValue({ bets: [] });
    vi.mocked(betsSummary).mockResolvedValue({ owners: [] });
    render(<BetsTab leagueId="L1" owners={owners} />);
    // Agate empty-state voice: say what *will* appear here, never that
    // something is missing (DESIGN.md § "Failure Is A Headline").
    expect(await screen.findByText(/no bets yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/every bet in the league, and who's paid up/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error when a ledger action fails", async () => {
    vi.mocked(updateBet).mockRejectedValue(new Error("boom"));
    render(<BetsTab leagueId="L1" owners={owners} />);
    await screen.findAllByText("+$500");
    fireEvent.click(screen.getAllByRole("button", { name: "Tom won" })[0]);
    expect(
      await screen.findByText(/couldn't update the bet/i),
    ).toBeInTheDocument();
  });

  it("clears an active season filter after recording a bet", async () => {
    vi.mocked(createBet).mockResolvedValue(settledBet);
    render(<BetsTab leagueId="L1" owners={owners} />);
    await screen.findAllByText("+$500");

    // Narrow to a season, then record a bet.
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    await waitFor(() =>
      expect(listBets).toHaveBeenLastCalledWith("L1", { season: 2026 }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Record a bet" }));
    fireEvent.change(screen.getByLabelText("Side A"), {
      target: { value: "u_tom" },
    });
    fireEvent.change(screen.getByLabelText("Side B"), {
      target: { value: "u_mike" },
    });
    fireEvent.change(screen.getByLabelText("Amount ($)"), {
      target: { value: "20" },
    });
    fireEvent.change(screen.getByLabelText("The bet"), {
      target: { value: "New wager" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save bet/i }));

    await waitFor(() => expect(createBet).toHaveBeenCalledTimes(1));
    // Filter resets to All seasons so the new bet is always visible.
    await waitFor(() =>
      expect(listBets).toHaveBeenLastCalledWith("L1", { season: undefined }),
    );
  });
});
