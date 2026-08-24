import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "../components/ThemeProvider";
import { ApiError } from "../lib/api";

// React's cache() (used to dedupe the page's ownerDetail call between
// generateMetadata and the body — see app/league/[id]/owner/[uid]/page.tsx)
// is only implemented by Next.js's patched React build; the plain `react`
// package this test runs against doesn't export it. Shim it as a pass-through
// so importing the page module doesn't crash — request-scoped memoization
// itself isn't what's under test here.
vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  cache: <T extends (...args: never[]) => unknown>(fn: T): T => fn,
}));

// Only the fetch is mocked — the page's branching on the error it throws is
// exactly what's under test here.
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  ownerDetail: vi.fn(),
}));
import { ownerDetail } from "../lib/api";

import OwnerPage from "../app/league/[id]/owner/[uid]/page";
import OwnerLoading from "../app/league/[id]/owner/[uid]/loading";

const PARAMS = { params: { id: "L1", uid: "u9" } };

/** OwnerPage is an async server component: await it, then render the tree
 *  (wrapped in ThemeProvider for the TopBar's theme toggle). */
async function renderPage(props: Parameters<typeof OwnerPage>[0]) {
  render(<ThemeProvider>{await OwnerPage(props)}</ThemeProvider>);
}

describe("OwnerPage error states", () => {
  beforeEach(() => {
    vi.mocked(ownerDetail).mockReset();
  });

  it("409 cold cache → 'not graded yet' with a dashboard link", async () => {
    vi.mocked(ownerDetail).mockRejectedValue(new ApiError(409, "cache cold"));
    await renderPage(PARAMS);
    expect(screen.getByText(/hasn't been graded yet/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open the league dashboard/i }),
    ).toHaveAttribute("href", "/league/L1");
    expect(screen.queryByText(/franchise not found/i)).not.toBeInTheDocument();
  });

  it("404 → keeps the not-found copy", async () => {
    vi.mocked(ownerDetail).mockRejectedValue(new ApiError(404, "unknown owner"));
    await renderPage(PARAMS);
    expect(screen.getByText("Franchise not found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to league/i }))
      .toHaveAttribute("href", "/league/L1");
  });

  it("500 → honest failure with a retry that preserves the deep link", async () => {
    vi.mocked(ownerDetail).mockRejectedValue(new ApiError(500, "boom"));
    await renderPage({ ...PARAMS, searchParams: { tab: "trades", year: "2023" } });
    expect(screen.getByText(/something broke on our end/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /try again/i }))
      .toHaveAttribute("href", "/league/L1/owner/u9?tab=trades&year=2023");
  });

  it("non-HTTP failures (network) also get the honest error, not 'not found'", async () => {
    vi.mocked(ownerDetail).mockRejectedValue(new TypeError("fetch failed"));
    await renderPage(PARAMS);
    expect(screen.getByText(/something broke on our end/i)).toBeInTheDocument();
    expect(screen.queryByText(/franchise not found/i)).not.toBeInTheDocument();
  });
});

describe("OwnerLoading", () => {
  it("announces the skeleton to screen readers", () => {
    render(<OwnerLoading />);
    expect(screen.getByText("Loading franchise…")).toBeInTheDocument();
  });
});
