import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import LeaguePage from "@/app/league/[id]/page";
import { ThemeProvider } from "@/components/ThemeProvider";

const push = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => searchParams,
}));

beforeEach(() => {
  push.mockClear();
  localStorage.clear();
  searchParams = new URLSearchParams();
  // Synthetic HTTP fixture; backend tests exercise the persisted phase and filtering.
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL(String(input), "http://localhost");
    let body: unknown = {};
    if (url.pathname === "/api/league/L1") {
      const year = url.searchParams.get("year");
      body = {
        league: { league_id: "L1", name: "Test League", season: 2026, total_rosters: 2, status: "active", seasons: [2024, 2026] },
        selected_year: year === "auto" ? 2026 : year === "all" ? "all" : Number(year),
        selected_lens: "ktc", phase: "regular", phase_season: 2026, phase_week: 5,
        hero_stats: {}, standings: [], latest_trades: [], headline_trades: [], records: {}, warnings: [],
      };
    } else if (url.pathname === "/api/me/leagues") {
      body = [];
    }
    return new Response(JSON.stringify(body), { status: 200 });
  });
});
afterEach(() => vi.restoreAllMocks());

function openPage(query = "") {
  searchParams = new URLSearchParams(query);
  render(<ThemeProvider><LeaguePage params={{ id: "L1" }} searchParams={Object.fromEntries(searchParams)} /></ThemeProvider>);
}

it("opens the unfiltered dashboard with the API's active season selected", async () => {
  // Mutation: the page converts an absent year to all before requesting the dashboard.
  openPage();
  const years = await screen.findByRole("group", { name: "Filter by season" });
  expect(within(years).getByRole("button", { name: "26" })).toHaveAttribute("aria-pressed", "true");
  expect(within(years).getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("columnheader", { name: /^Finish/i })).toBeInTheDocument();
});

it("shows a stopped data job without inviting repeated cold-cache submissions", async () => {
  const normal = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path === "/api/league/L1") return new Response(JSON.stringify({ detail: "cache cold" }), { status: 409 });
    if (path === "/api/league/L1/refresh-jobs") return new Response(JSON.stringify({
      id: "stopped-job", state: "needs_attention", reason: "execution_failed", progress: {},
    }), { status: 202 });
    return normal(input, init);
  });
  openPage();
  await screen.findByText(/The refresh needs attention/);
  expect(screen.queryByRole("button", { name: /Try again/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "Building your league" })).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.filter(([url, init]) =>
    String(url).endsWith("/refresh-jobs") && init?.method === "POST")).toHaveLength(1);
});

it("keeps Owners all-time without turning its default into an explicit All choice on return", async () => {
  // Mutation: give navigation the fallback data year instead of the URL selection.
  openPage("tab=owners");
  await screen.findByRole("navigation", { name: "League sections" });
  for (const link of screen.getAllByRole("link", { name: /^Franchises$/i })) {
    expect(new URL(link.getAttribute("href")!, "http://localhost").searchParams.has("year")).toBe(false);
  }
  // The outgoing request must still load all owners for this career-wide view.
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url) === "/api/league/L1?year=all&lens=ktc")).toBe(true);
});

it.each(["all", "2024"])("keeps explicit year=%s selected through rendering, sorting, and both navigation menus", async (year) => {
  // Mutation: default over an explicit year, or drop it in sorting/mobile/desktop links.
  openPage(`year=${year}`);
  const years = await screen.findByRole("group", { name: "Filter by season" });
  expect(within(years).getByRole("button", { name: year === "all" ? "All" : "24" })).toHaveAttribute("aria-pressed", "true");
  for (const link of screen.getAllByRole("link", { name: /^Trades$/i })) {
    expect(new URL(link.getAttribute("href")!, "http://localhost").searchParams.get("year")).toBe(year);
  }
  fireEvent.click(screen.getByRole("button", { name: /^Sort by Rec/ }));
  await waitFor(() => expect(push).toHaveBeenCalled());
  expect(new URL(push.mock.calls.at(-1)![0], "http://localhost").searchParams.get("year")).toBe(year);
});
