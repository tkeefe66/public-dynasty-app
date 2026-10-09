import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HomePage from "@/app/page";
import { DashboardClient } from "@/components/DashboardClient";
import { ApiError, dashboard, getMe, getProfiles, myLeagues, type MyLeague } from "@/lib/api";

vi.mock("@/auth", () => ({ signOut: vi.fn() }));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  dashboard: vi.fn(),
  myLeagues: vi.fn(),
  getProfiles: vi.fn().mockResolvedValue({}),
  getMe: vi.fn().mockResolvedValue({ is_admin: false, sleeper_user_id: null }),
}));

function league(id: string, state?: string, warm = false): MyLeague {
  return {
    league_id: id, name: id, season: null, warm, sleeper_roster_id: null,
    added_at: "2026-10-09T04:10:42Z",
    refresh_job: state ? { id: `${id}-job`, state, reason: "execution_failed" } : null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(dashboard).mockRejectedValue(new ApiError(409, "cache cold"));
  vi.mocked(getProfiles).mockResolvedValue({});
  vi.mocked(getMe).mockResolvedValue({ is_admin: false, sleeper_user_id: null,
    email: "member@example.test", name: null, avatar_url: null, sleeper_username: null });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("League refresh status", () => {
  it("distinguishes an idle import, active builds, and failures on My Leagues", async () => {
    vi.mocked(myLeagues).mockResolvedValue([
      league("Ready league", "succeeded", true),
      league("New league"),
      league("Queued league", "queued"),
      league("Building league", "running"),
      league("Example Yahoo League", "needs_attention"),
      league("Paused league", "held"),
      league("Updating league", "running", true),
      league("Failed update", "needs_attention", true),
    ]);
    await act(async () => { render(await HomePage()); });
    for (const [name, status] of [
      ["Ready league", "Ready"], ["New league", "Not built"],
      ["Queued league", "Queued"], ["Building league", "Building"],
      ["Example Yahoo League", "Needs attention"], ["Paused league", "Paused"],
      ["Updating league", "Updating"], ["Failed update", "Needs attention"],
    ]) {
      expect(screen.getByRole("link", { name: `${name} ${status}` })).toBeInTheDocument();
    }
    expect(screen.queryByText("Warming")).toBeNull();
    expect(screen.queryByText("execution_failed")).toBeNull();
  });

  it("checks a failed first build without resubmitting on mount, filter changes, or Check status", async () => {
    vi.mocked(myLeagues).mockResolvedValue([league("470.l.123456", "needs_attention")]);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({
      id: "470.l.123456-job", state: "needs_attention", reason: "execution_failed", progress: {},
    })));
    const props = { leagueId: "470.l.123456", initialYear: "auto" as const,
      initialLens: "ktc" as const, initialTab: "dashboard" as const };
    const view = render(<StrictMode><DashboardClient {...props} /></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: "Check status" }));
    await screen.findByRole("button", { name: "Check status" });
    view.rerender(<StrictMode><DashboardClient {...props} initialYear={2025} /></StrictMode>);
    await screen.findByRole("button", { name: "Check status" });
    expect(screen.queryByRole("dialog", { name: "Building your league" })).toBeNull();
    expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(3);
    for (const [url, init] of fetchSpy.mock.calls) {
      expect(url).toMatch(/refresh-jobs\/470.l.123456-job$/);
      expect(init?.method).toBeUndefined();
    }
  });

  it("submits a new league once under Strict Mode and stops after its build fails", async () => {
    vi.mocked(myLeagues).mockResolvedValue([league("470.l.123456")]);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({
      id: "new-job", state: "needs_attention", reason: "execution_failed", progress: {},
    }), { status: 202 }));
    const view = render(<StrictMode><DashboardClient leagueId="470.l.123456"
      initialYear="auto" initialLens="ktc" initialTab="dashboard" /></StrictMode>);
    await screen.findByRole("button", { name: "Check status" });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][1]?.method).toBe("POST");
    vi.mocked(myLeagues).mockResolvedValue([league("470.l.123456", "needs_attention")]);
    view.rerender(<StrictMode><DashboardClient leagueId="470.l.123456"
      initialYear={2025} initialLens="ktc" initialTab="dashboard" /></StrictMode>);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    expect(fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    await screen.findByRole("button", { name: "Check status" });
  });

  it("does not launch a refresh when the membership status cannot be read", async () => {
    vi.mocked(myLeagues).mockRejectedValue(new Error("status unavailable"));
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<DashboardClient leagueId="470.l.123456" initialYear="auto"
      initialLens="ktc" initialTab="dashboard" />);
    await screen.findByText(/couldn't check the refresh status/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("stops browser polling when an active build page is left", async () => {
    vi.useFakeTimers();
    vi.mocked(myLeagues).mockResolvedValue([league("470.l.123456", "running")]);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({
      id: "470.l.123456-job", state: "running", reason: "", progress: { stage: "chain" },
    })));
    let view: ReturnType<typeof render>;
    await act(async () => {
      view = render(<DashboardClient leagueId="470.l.123456" initialYear="auto"
        initialLens="ktc" initialTab="dashboard" />);
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    view!.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("only starts a replacement for a stopped job after an explicit retry", async () => {
    vi.mocked(myLeagues).mockResolvedValue([league("470.l.123456", "cancelled")]);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => new Response(JSON.stringify({
      id: "470.l.123456-job", state: init?.method === "POST" ? "needs_attention" : "cancelled",
      reason: "", progress: {},
    })));
    render(<DashboardClient leagueId="470.l.123456" initialYear="auto"
      initialLens="ktc" initialTab="dashboard" />);
    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(fetchSpy.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
    fireEvent.click(retry);
    await screen.findByRole("button", { name: "Check status" });
    expect(fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });
});
