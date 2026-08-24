import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { TopBar } from "@/components/TopBar";
import { PRODUCT_NAME } from "@/lib/brand";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// LeagueSwitcher fetches its league list on mount. These tests care WHERE it
// sits in the strip, not what it lists, so it stands in as a marker — which
// also keeps its async state update out of the test (an unwrapped-act warning).
// Mocking the module still fails the order test if TopBar stops rendering it.
vi.mock("@/components/LeagueSwitcher", () => ({
  LeagueSwitcher: () => <span data-testid="league-switcher" />,
}));

// WeekNote renders nothing out of season; keep it inert either way.
vi.mock("@/components/WeekNote", () => ({ WeekNote: () => null }));

// ThemeToggle needs a ThemeProvider context. These tests are about the strip's
// STRUCTURE — what is in it and in what order — so stand it in with a marker
// rather than mounting the provider just to satisfy a hook.
vi.mock("@/components/ThemeToggle", () => ({
  ThemeToggle: () => <span data-testid="theme-toggle" />,
}));

/**
 * The chrome strip, against `.design/components/ledger/TopBar.prompt.md` and
 * the approved information architecture.
 *
 * The strip is now: wordmark · league · FIVE inline destinations (Franchises,
 * Trades, Owners, Bets, Draft) · the right group (theme toggle + a utility
 * sheet holding How this works and Settings).
 *
 * Three things these tests hold down, each of which broke once already:
 *
 *   1. The league sits BESIDE the wordmark, not in the right group. On a phone
 *      the old placement pushed league identity onto a third line next to the
 *      theme toggle — furthest from where the eye lands.
 *   2. How this works and Settings are in the sheet at EVERY width. An item
 *      that moves between a nav and a menu depending on width is two different
 *      information architectures.
 *   3. Below 701px the inline run is not rendered at all — the phone's
 *      destinations come from the dashboard tab bar, and two navs for the same
 *      places is one nav too many.
 *
 * Draft-specific assertions (route shape, no icon) live in `draft-nav.test.tsx`.
 */
const INLINE_LABELS = ["Franchises", "Trades", "Owners", "Bets", "Draft"];
const SHEET_LABELS = ["How this works", "Settings"];

describe("TopBar", () => {
  // The strip REMEMBERS the last league in localStorage and every test in this
  // file shares one jsdom, so a test that ran with `leagueId="L1"` leaves a
  // league in context for the next one. Clearing it is what makes the
  // outside-a-league case actually be outside a league.
  beforeEach(() => localStorage.clear());

  it("renders exactly the five league destinations inline", () => {
    render(<TopBar leagueId="L1" activeNav="dashboard" />);
    for (const label of INLINE_LABELS) {
      expect(screen.getByRole("link", { name: new RegExp(`^${label}$`, "i") })).toBeTruthy();
    }
    // The old six-item run is gone: these two are housekeeping, not places you
    // go to look at the league, and they live behind the utility control.
    for (const label of SHEET_LABELS) {
      expect(screen.queryByRole("link", { name: new RegExp(`^${label}$`, "i") })).toBeNull();
    }
  });

  it("keeps How this works and Settings in the utility sheet", () => {
    render(<TopBar leagueId="L1" activeNav="dashboard" />);
    const trigger = screen.getByRole("button", { name: /menu/i });
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    const methodology = screen.getByRole("menuitem", { name: /^How this works$/i });
    const settings = screen.getByRole("menuitem", { name: /^Settings$/i });
    expect(methodology.getAttribute("href")).toBe("/methodology");
    expect(settings.getAttribute("href")).toBe("/league/L1/settings");
  });

  it("moves focus into the sheet on open and back to the trigger on Escape", () => {
    render(<TopBar leagueId="L1" activeNav="dashboard" />);
    const trigger = screen.getByRole("button", { name: /menu/i });

    fireEvent.click(trigger);
    expect(document.activeElement).toBe(screen.getByRole("menuitem", { name: /^How this works$/i }));

    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes the sheet on an outside click", () => {
    render(<TopBar leagueId="L1" activeNav="dashboard" />);
    fireEvent.click(screen.getByRole("button", { name: /menu/i }));
    expect(screen.queryByRole("menu")).not.toBeNull();

    act(() => {
      fireEvent.mouseDown(document.body);
    });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  /* INVERTED. This used to assert the league chip sat beside the wordmark,
   * which was right while `TopBar` was the only persistent chrome. The masthead
   * now hosts `LeagueSwitcher` as the nameplate itself, so a chip here would
   * state the league TWICE on one screen — and did, briefly, because two agents
   * each left it alone rather than fight for this file. Same intent as before,
   * "the league is named once and in the right place", opposite evidence. */
  it("carries NO league chip — the masthead is the league", () => {
    const { container } = render(<TopBar leagueId="L1" activeNav="dashboard" />);
    expect(screen.queryByTestId("league-switcher")).toBeNull();
    expect(container.querySelector("header nav")!.textContent).not.toMatch(/switch league/i);
  });

  it("marks the active destination and only that one", () => {
    render(<TopBar leagueId="L1" activeNav="trades" />);
    const active = screen.getByRole("link", { name: /^Trades$/i });
    expect(active.className).toMatch(/font-bold/);
    expect(screen.getByRole("link", { name: /^Bets$/i }).className).not.toMatch(/font-bold/);
  });

  it("keeps the renamed items pointing where they always did", () => {
    // The LABELS changed (Dashboard → Franchises, Franchises → Owners); the
    // keys and destinations did not, which is what keeps every existing
    // `activeNav={tab}` call site correct.
    render(<TopBar leagueId="L1" activeNav="owners" />);
    expect(screen.getByRole("link", { name: /^Franchises$/i }).getAttribute("href")).toBe("/league/L1");
    const owners = screen.getByRole("link", { name: /^Owners$/i });
    expect(owners.getAttribute("href")).toBe("/league/L1?tab=owners");
    expect(owners.className).toMatch(/font-bold/);
  });

  it("shows no league nav outside a league", () => {
    // My Leagues / Account / Admin: the four destinations are league-context,
    // so the strip is the wordmark and the right group. How this works is NOT
    // league-context and stays reachable in the sheet; Settings is, so it is
    // absent rather than pointing at a dead "#".
    render(<TopBar />);
    for (const label of INLINE_LABELS) {
      expect(screen.queryByRole("link", { name: new RegExp(`^${label}$`, "i") })).toBeNull();
    }
    fireEvent.click(screen.getByRole("button", { name: /menu/i }));
    expect(screen.getByRole("menuitem", { name: /^How this works$/i })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /^Settings$/i })).toBeNull();
  });

  it("remembers the last league for the sheet's Settings row", () => {
    // The league-context memory is what lets chrome outside a league still
    // point somewhere real. Written by a league render, read by the next one.
    render(<TopBar leagueId="L9" year="2024" lens="ktc" activeNav="dashboard" />);
    expect(JSON.parse(localStorage.getItem("last_league_ctx")!)).toEqual({
      leagueId: "L9",
      year: "2024",
      lens: "ktc",
    });

    render(<TopBar />);
    fireEvent.click(screen.getAllByRole("button", { name: /menu/i })[1]);
    expect(
      screen.getByRole("menuitem", { name: /^Settings$/i }).getAttribute("href"),
    ).toBe("/league/L9/settings");
  });

  it("does not render the inline nav below 701px", () => {
    // `hidden min-[701px]:flex` — not a wrap. The run does not exist on a
    // phone, so it cannot occupy a second line of chrome above the content;
    // the mobile tab bar in the dashboard body carries the same four places.
    const { container } = render(<TopBar leagueId="L1" activeNav="dashboard" />);
    const navGroup = Array.from(container.querySelectorAll("header nav > div")).find(
      (el) => el.textContent?.includes("Franchises"),
    )!;
    expect(navGroup.className).toMatch(/\bhidden\b/);
    expect(navGroup.className).toMatch(/min-\[701px\]:flex/);
    // The old phone wrap trick is gone with the wrap it managed.
    expect(navGroup.className).not.toMatch(/basis-full/);
    expect(navGroup.className).not.toMatch(/order-last/);
  });

  it("keeps a button out of a link", () => {
    // A <button> inside an <a> is not valid HTML and swallows the link's
    // activation. The sheet's rows are links; its trigger is a sibling button.
    const { container } = render(<TopBar leagueId="L1" activeNav="dashboard" />);
    fireEvent.click(screen.getByRole("button", { name: /menu/i }));
    expect(container.querySelectorAll("a button").length).toBe(0);
    expect(container.querySelectorAll("button a").length).toBe(0);
  });
});
