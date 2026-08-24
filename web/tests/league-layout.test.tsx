import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import LeagueLayout from "../app/league/[id]/layout";

const myLeagues = vi.fn();
vi.mock("@/lib/api", () => ({ myLeagues: () => myLeagues() }));

async function renderLayout(id: string) {
  render(await LeagueLayout({ children: <div>page</div>, params: { id } }));
}

const league = (league_id: string) => ({
  league_id, name: "L", season: 2026, warm: true,
  sleeper_roster_id: null, added_at: "",
});

describe("league layout — admin access banner", () => {
  // Block body, NOT `() => myLeagues.mockReset()`: mockReset returns the mock,
  // vi.fn() is callable, and vitest treats a function returned from a hook as a
  // TEARDOWN callback — so it would call the mock again after each test. With a
  // throwing implementation installed that teardown call rejects with nothing
  // awaiting it, failing the test for a reason that has nothing to do with the
  // code under test.
  beforeEach(() => {
    myLeagues.mockReset();
  });

  it("is absent on a league you belong to", async () => {
    myLeagues.mockResolvedValue([league("L1")]);
    await renderLayout("L1");
    expect(screen.queryByText(/admin access/i)).toBeNull();
    expect(screen.getByText("page")).toBeTruthy();
  });

  it("warns when the league is not one of yours", async () => {
    myLeagues.mockResolvedValue([league("L-OTHER")]);
    await renderLayout("L1");
    expect(screen.getByText(/admin access/i)).toBeTruthy();
    expect(screen.getByText(/read-only/i)).toBeTruthy();
  });

  it("warns when the leagues call fails — over-warning is the safe direction", async () => {
    // mockImplementation, not mockRejectedValue: the latter constructs the
    // rejected promise at setup time, which Node flags as unhandled before the
    // layout ever awaits it.
    myLeagues.mockImplementation(async () => {
      throw new Error("boom");
    });
    await renderLayout("L1");
    expect(screen.getByText(/admin access/i)).toBeTruthy();
  });

  it("still renders the page underneath the banner", async () => {
    myLeagues.mockResolvedValue([]);
    await renderLayout("L1");
    expect(screen.getByText("page")).toBeTruthy();
  });
});
