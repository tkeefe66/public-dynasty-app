/**
 * ADDED IN REVIEW. The rebuilt settings page carries three independent
 * try/catch blocks now (owner names, profile, membership row) and the admin
 * gate is the one that must FAIL CLOSED — a getMe() that throws must never
 * reveal the Data or LLM Spend sections. Nothing in
 * SettingsPhoneLayout.test.tsx renders the page, so that contract was
 * untested after the rebuild.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import SettingsPage from "../app/league/[id]/settings/page";

const getOwnerNames = vi.fn();
const getMe = vi.fn();
const myLeagues = vi.fn();

vi.mock("@/lib/api", () => ({
  getOwnerNames: (...a: unknown[]) => getOwnerNames(...a),
  getMe: (...a: unknown[]) => getMe(...a),
  myLeagues: (...a: unknown[]) => myLeagues(...a),
  refreshStream: vi.fn(),
  putOwnerNames: vi.fn(),
}));

vi.mock("@/components/TopBar", () => ({
  TopBar: () => <div data-testid="topbar" />,
}));
vi.mock("@/components/LlmCostPanel", () => ({
  LlmCostPanel: () => <div data-testid="llm-cost-panel" />,
}));

const OWNERS = {
  owners: [{ user_id: "u1", sleeper_name: "tkeefe", display_name: "Tom" }],
};

async function renderPage() {
  render(await SettingsPage({ params: { id: "L1" } }));
}

beforeEach(() => {
  getOwnerNames.mockReset();
  getMe.mockReset();
  myLeagues.mockReset();
  getOwnerNames.mockResolvedValue(OWNERS);
  myLeagues.mockResolvedValue([
    { league_id: "L1", name: "The League", season: 2026, warm: true, sleeper_roster_id: null, added_at: "" },
  ]);
});

describe("settings page — admin gating fails closed", () => {
  it("shows Data + LLM Spend for an admin", async () => {
    getMe.mockResolvedValue({ is_admin: true });
    await renderPage();
    expect(screen.getByRole("button", { name: "Refresh data" })).toBeTruthy();
    expect(screen.getByTestId("llm-cost-panel")).toBeTruthy();
  });

  it("hides both for a non-admin", async () => {
    getMe.mockResolvedValue({ is_admin: false });
    await renderPage();
    expect(screen.queryByRole("button", { name: "Refresh data" })).toBeNull();
    expect(screen.queryByTestId("llm-cost-panel")).toBeNull();
  });

  it("hides both when getMe() throws — fail closed, not open", async () => {
    // mockImplementation, not mockRejectedValue: the latter builds the rejected
    // promise at setup time and Node flags it unhandled before the page awaits.
    getMe.mockImplementation(async () => {
      throw new Error("no session");
    });
    await renderPage();
    expect(screen.queryByRole("button", { name: "Refresh data" })).toBeNull();
    expect(screen.queryByTestId("llm-cost-panel")).toBeNull();
    // The page still renders the thing it is FOR.
    expect(screen.getByLabelText("tkeefe")).toBeTruthy();
  });

  it("keeps the empty state reachable when owner names fail to load", async () => {
    getMe.mockResolvedValue({ is_admin: false });
    getOwnerNames.mockImplementation(async () => {
      throw new Error("409 cache cold");
    });
    await renderPage();
    expect(screen.getByText("League not loaded yet. Run a refresh first.")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("does not let a failed membership lookup take the page down", async () => {
    getMe.mockResolvedValue({ is_admin: true });
    myLeagues.mockImplementation(async () => {
      throw new Error("boom");
    });
    await renderPage();
    // Kicker degrades to the owner count alone rather than guessing a name.
    // NOTE: getAllByText, because "1 owner" is rendered TWICE — the page kicker
    // and the section's meta line both print the same count.
    expect(screen.getAllByText("1 owner").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Refresh data" })).toBeTruthy();
  });
});
