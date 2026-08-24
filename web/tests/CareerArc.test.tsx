import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { CareerArc } from "@/components/CareerArc";
import type { SeasonArc } from "@/lib/types";

/**
 * The career-arc chart, ported from Agate (2026-08-16). It had NO test at all,
 * which is how both of the bugs below survived — they are visible on the live
 * league's #1 franchise and nothing objected.
 *
 * The data here is that franchise's real four seasons, trimmed to what matters:
 *  - Toilet Bowl is 0.0 in EVERY season. Normal, and a good sign — this owner
 *    never reached the consolation bracket. It used to draw as four 2px stubs
 *    on an axis, which reads as a chart that failed to load.
 *  - 2026 has trades but no points, because it has not been played. So the
 *    NEWEST bar — the one the eye goes to — was a stub on every production
 *    metric through every offseason. The app's rule everywhere else is "null is
 *    not 0"; this chart had no way to say it.
 */
const season = (s: number, p: Partial<SeasonArc>): SeasonArc => ({
  season: s, net_ktc: 0, production_total: 0, production_regular: 0,
  production_playoff: 0, production_toilet: 0, trades: 3, ...p,
});

const ARC: SeasonArc[] = [
  season(2023, { net_ktc: 40523, production_total: 2418.9, production_started: 2346.9,
                 production_regular: 1983.9, production_playoff: 319.8, trades: 4 }),
  season(2024, { net_ktc: 24649, production_total: 662.4, production_started: 102.5,
                 production_regular: 41.2, production_playoff: 61.3 }),
  season(2025, { net_ktc: 18038, production_total: 231.2, production_started: 153.1,
                 production_regular: 132.3, production_playoff: 20.8 }),
  // Unplayed: trades on the books, no points anywhere.
  season(2026, { net_ktc: 17163, production_started: 0 }),
];

const rows = () => within(screen.getByTestId("career-arc-rows"));

describe("CareerArc", () => {
  it("charts Started Points alongside the five", () => {
    // It shipped as a column in both ledgers and was not in this chart, so the
    // franchise page could rank you on a metric it would not draw.
    render(<CareerArc arc={ARC} />);
    expect(screen.getAllByText(/Started/).length).toBeGreaterThan(0);
  });

  it("says an all-zero metric never happened, instead of drawing stubs", () => {
    render(<CareerArc arc={ARC} />);
    // Toilet Bowl is 0.0 in all four seasons.
    expect(screen.getAllByText(/Never reached it/i).length).toBeGreaterThan(0);
  });

  it("does not claim a metric is empty when it has real values", () => {
    // The empty state must key on the DATA, not on the metric's name — a
    // franchise that did reach the consolation bracket has a real chart.
    const withToilet = ARC.map((s) =>
      s.season === 2024 ? { ...s, production_toilet: 88.4 } : s);
    render(<CareerArc arc={withToilet} />);
    expect(screen.queryByText(/Never reached it/i)).toBeNull();
  });

  it("hatches an unplayed season rather than drawing it as zero", () => {
    const { container } = render(<CareerArc arc={ARC} />);
    const hatched = Array.from(container.querySelectorAll<HTMLElement>("[title]"))
      .filter((el) => (el.getAttribute("title") ?? "").includes("not played yet"));
    expect(hatched.length).toBeGreaterThan(0);
    // It is a hatch, not a bar: no signed fill, so it cannot read as an outcome.
    for (const el of hatched) {
      expect(el.className).not.toMatch(/bg-(pos|neg)-bar/);
      expect(el.style.backgroundImage).toMatch(/repeating-linear-gradient/);
    }
  });

  it("treats a PAST season that scored nothing as a real zero", () => {
    // Only the newest season can be in progress. An older one that genuinely
    // produced nothing keeps its stub — it played, and produced nothing.
    const played = ARC.map((s) =>
      s.season === 2026 ? { ...s, production_total: 12.5, production_started: 12.5 } : s);
    const { container } = render(<CareerArc arc={played} />);
    const hatched = Array.from(container.querySelectorAll<HTMLElement>("[title]"))
      .filter((el) => (el.getAttribute("title") ?? "").includes("not played yet"));
    expect(hatched).toHaveLength(0);
  });

  it("gives the phone a row per metric, each carrying its own figure", () => {
    /* The rows have NO zero axis, so sign has to survive without one — colour
     * may never be the only carrier. That is why the latest figure travels with
     * every row rather than living in a tooltip. */
    render(<CareerArc arc={ARC} />);
    expect(rows().getAllByText(/Trade Value/).length).toBeGreaterThan(0);
    expect(rows().getAllByText(/\+40,523|17,163/).length).toBeGreaterThan(0);
  });

  it("still explains itself with no seasons at all", () => {
    render(<CareerArc arc={[]} />);
    expect(screen.getByText(/once this franchise has made a trade/i)).toBeTruthy();
  });

  it("does NOT hatch Trade Value in an unplayed season", () => {
    /* Caught by looking at it live. Trade Value is market value, real the
     * moment a trade lands — this franchise's 2026 figure is 17,163, close to
     * 2025's 18,038. Hatching every metric hid a genuine number behind a
     * "not played yet" mark. Only points need a game to have been played. */
    const { container } = render(<CareerArc arc={ARC} />);
    const hatched = Array.from(container.querySelectorAll<HTMLElement>("[title]"))
      .filter((el) => (el.getAttribute("title") ?? "").includes("not played yet"));
    /* FOUR, not five. There are five production metrics, but Toilet Bowl is
     * all-zero here so it renders the empty state and has no bars at all —
     * the two behaviours compose. Trade Value is the one that draws a real
     * 2026 bar, and that is the point of this test. */
    expect(hatched).toHaveLength(4);
    // The Trade Value chart still draws its 2026 value.
    const titles = Array.from(container.querySelectorAll<HTMLElement>("[title]"))
      .map((el) => el.getAttribute("title") ?? "");
    expect(titles).toContain("2026: +17,163");
  });

  it("reports an unplayed latest as unknown, not as zero", () => {
    // The sparkline drew "no data" while the figure beside it said 0.0 — the
    // same null-is-not-0 violation the hatch exists to prevent.
    render(<CareerArc arc={ARC} />);
    const list = screen.getByTestId("career-arc-rows");
    const started = Array.from(list.children).find((c) =>
      (c.textContent ?? "").startsWith("Started"));
    expect(started?.textContent).not.toMatch(/0\.0/);
    expect(started?.textContent).toMatch(/—/);
    // Trade Value still reports its real latest.
    const value = Array.from(list.children).find((c) =>
      (c.textContent ?? "").startsWith("Trade Value"));
    expect(value?.textContent).toMatch(/17,163/);
  });
});
