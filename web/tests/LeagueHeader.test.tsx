import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeagueHeader, phaseLabel } from "@/components/LeagueHeader";
import type { LeagueSummary } from "@/lib/types";

/**
 * The masthead, against `.design/components/ledger/StampBand.jsx`.
 *
 * Three things are asserted because all three were wrong or absent before:
 *
 *   1. It is a ROUNDED PANEL. It used to cancel `Shell`'s padding with negative
 *      margins so the cobalt bled to both page edges — Agate's rule, still
 *      cited in the docstring long after Agate was retired.
 *   2. The folio ends in the league's calendar PHASE, not a seconds-precise
 *      refresh timestamp, and renders that segment only once it is known.
 *   3. The league NAME is the switcher, so the league is stated once per
 *      screen rather than twice.
 */

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

// The switcher's own list. It is re-hosted here, not reimplemented, so it still
// fetches on mount — stub the module so these tests are about WHERE it lives.
vi.mock("@/lib/api", () => ({
  myLeagues: () =>
    Promise.resolve([
      { league_id: "L1", name: "Bloodbath Dynasty" },
      { league_id: "L2", name: "The Other One" },
    ]),
  getMe: () => Promise.resolve({ is_admin: false }),
}));

const LEAGUE: LeagueSummary = {
  league_id: "L1",
  name: "Bloodbath Dynasty",
  season: 2026,
  total_rosters: 12,
  status: "in_season",
  last_refreshed: "2026-08-14T20:35:01Z",
};

function mockState(body: unknown, ok = true) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok, json: () => Promise.resolve(body) }));
}

/** The folio line — the one `<p>` in the band. */
function folio(container: HTMLElement): string {
  return container.querySelector("p")!.textContent!;
}

beforeEach(() => {
  push.mockReset();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("phaseLabel", () => {
  it("maps each season_type to its drawn word", () => {
    expect(phaseLabel({ season_type: "off" })).toBe("Offseason");
    expect(phaseLabel({ season_type: "pre" })).toBe("Preseason");
    expect(phaseLabel({ season_type: "post" })).toBe("Postseason");
    expect(phaseLabel({ season_type: "regular", week: 14 })).toBe("Week 14");
  });

  it("is null whenever the phase is not knowable — never a guess", () => {
    expect(phaseLabel(null)).toBeNull();
    expect(phaseLabel(undefined)).toBeNull();
    expect(phaseLabel({})).toBeNull();
    expect(phaseLabel({ season_type: "regular" })).toBeNull();
    expect(phaseLabel({ season_type: "regular", week: 0 })).toBeNull();
    expect(phaseLabel({ season_type: "postseason-ish" })).toBeNull();
  });
});

describe("LeagueHeader — the band", () => {
  it("is a rounded panel on the stamp ground, not a full-bleed slab", () => {
    mockState({ season_type: "off", week: 1 });
    const { container } = render(<LeagueHeader league={LEAGUE} totalTrades={47} />);
    const band = container.firstElementChild as HTMLElement;

    expect(band.className).toContain("rounded-panel");
    expect(band.className).toContain("bg-stamp");
    // The negative margins that cancelled Shell's padding are the full-bleed
    // mechanism. Their absence IS the rounded-panel decision.
    expect(band.className).not.toMatch(/(^|\s)-mx-/);
  });

  it("reverses type out of the ground with the drawn second ink, never an alpha", () => {
    mockState({ season_type: "off" });
    const { container } = render(<LeagueHeader league={LEAGUE} totalTrades={47} />);
    const band = container.firstElementChild as HTMLElement;
    expect(band.className).toContain("text-stamp-ink");
    // `--stamp-ink-dim` at 5.08:1, not `text-stamp-ink/70` at 3.97:1.
    expect(container.querySelector("p")!.className).toContain("text-stamp-ink-dim");
    expect(container.innerHTML).not.toMatch(/stamp-ink\/\d/);
  });
});

describe("LeagueHeader — the phase segment", () => {
  it("ends the folio in the phase once it is known", async () => {
    mockState({ season: "2026", season_type: "regular", week: 14 });
    const { container } = render(<LeagueHeader league={LEAGUE} totalTrades={47} />);
    await waitFor(() =>
      expect(folio(container)).toBe("12 teams · 47 trades graded · Week 14"),
    );
  });

  it("names each phase the way the design system does", async () => {
    for (const [state, word] of [
      [{ season_type: "off" }, "Offseason"],
      [{ season_type: "pre" }, "Preseason"],
      [{ season_type: "post" }, "Postseason"],
    ] as const) {
      mockState(state);
      const { container, unmount } = render(<LeagueHeader league={LEAGUE} totalTrades={47} />);
      await waitFor(() => expect(folio(container)).toBe(`12 teams · 47 trades graded · ${word}`));
      unmount();
    }
  });

  it("renders NOTHING for the segment until the phase is known — no flash, no guess", async () => {
    // A fetch that never settles: this is the first paint, every paint.
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    const { container } = render(<LeagueHeader league={LEAGUE} totalTrades={47} />);
    expect(folio(container)).toBe("12 teams · 47 trades graded");
    expect(folio(container)).not.toContain("·  ");
    // Let the switcher's own on-mount fetch settle inside act(), then confirm
    // the folio still says nothing about the phase.
    await waitFor(() => expect(folio(container)).toBe("12 teams · 47 trades graded"));
  });

  it("stays silent when the request fails or the phase is unreadable", async () => {
    for (const arrange of [
      () => mockState(null, false),
      () => vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline"))),
      () => mockState({ season_type: "regular", week: null }),
    ]) {
      arrange();
      const { container, unmount } = render(<LeagueHeader league={LEAGUE} totalTrades={47} />);
      await waitFor(() => expect(fetch).toHaveBeenCalled());
      expect(folio(container)).toBe("12 teams · 47 trades graded");
      unmount();
      vi.unstubAllGlobals();
    }
  });

  it("no longer prints a refresh timestamp", async () => {
    mockState({ season_type: "off" });
    const { container } = render(<LeagueHeader league={LEAGUE} totalTrades={47} />);
    await waitFor(() => expect(folio(container)).toContain("Offseason"));
    expect(folio(container)).not.toMatch(/refreshed/i);
    expect(folio(container)).not.toMatch(/\d{1,2}:\d{2}/);
  });
});

describe("LeagueHeader — the switcher lives in the masthead", () => {
  it("makes the league name the picker", async () => {
    mockState({ season_type: "off" });
    const { container } = render(<LeagueHeader league={LEAGUE} totalTrades={47} />);

    const trigger = screen.getByRole("button", { name: /bloodbath dynasty.*switch league/i });
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    // It IS the nameplate: the h1 in the band contains the control.
    expect(within(container.querySelector("h1")!).getByRole("button")).toBe(trigger);
    // Nameplate tiering is unchanged and still applied to the label.
    expect(trigger.textContent).toContain("Bloodbath Dynasty");
    expect(trigger.innerHTML).toContain("--nameplate-");
    // 44px effective target regardless of tier.
    expect(trigger.className).toContain("min-h-tap");
  });

  it("names the league from props, so it is right on the first paint", async () => {
    // `myLeagues()` has not resolved yet — the masthead must not read "League".
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<LeagueHeader league={{ ...LEAGUE, name: "Unlisted League" }} totalTrades={0} />);
    expect(screen.getByRole("button", { name: /unlisted league/i })).toBeTruthy();
    // …and stays right once the list arrives without this league in it.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /unlisted league/i })).toBeTruthy(),
    );
  });

  it("still opens its list, and still closes on Escape", async () => {
    mockState({ season_type: "off" });
    const user = userEvent.setup();
    render(<LeagueHeader league={LEAGUE} totalTrades={47} />);

    const trigger = screen.getByRole("button", { name: /switch league/i });
    await user.click(trigger);

    const menu = await screen.findByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "The Other One" })).toBeTruthy();
    expect(within(menu).getByRole("menuitem", { name: /my leagues/i })).toBeTruthy();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  });
});
