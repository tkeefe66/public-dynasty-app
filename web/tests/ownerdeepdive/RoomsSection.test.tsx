import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import {
  RoomsSection, assignLanes, laneSepPct, labelAnchorPx,
} from "@/components/ownerdeepdive/RosterHealthTab";
import type { OutlookView } from "@/lib/types";

function outlook(
  own: Record<string, number>, league: Record<string, number>,
): OutlookView {
  return {
    window: "Contending",
    age_profile: {
      avg_age_by_position: own,
      league_avg_age_by_position: league,
      overall_avg_age: 26,
      aging_risks: [],
      core_young: [],
    },
    draft_capital: {
      picks_by_season: {}, picks_by_season_round: {},
      net_vs_average: 0, status: "neutral", total_value: 0,
    },
    draft_needs: [],
  } as unknown as OutlookView;
}

describe("assignLanes", () => {
  it("puts two labels closer than the separation onto different lanes", () => {
    // Two rooms 0.1 years apart on a ±2yr axis = 2.5 percentage points.
    expect(assignLanes([48.75, 51.25], 11)).toEqual([0, 1]);
  });

  it("keeps well-separated labels on one lane", () => {
    expect(assignLanes([10, 40, 70, 95], 11)).toEqual([0, 0, 0, 0]);
  });

  it("opens a third lane when two are already occupied nearby", () => {
    expect(assignLanes([50, 51, 52], 11)).toEqual([0, 1, 2]);
  });

  it("reuses lane 0 once the gap reopens", () => {
    expect(assignLanes([50, 51, 70], 11)).toEqual([0, 1, 0]);
  });

  it("returns an empty array for no dots", () => {
    expect(assignLanes([], 11)).toEqual([]);
  });

  it("puts a lone dot on lane 0 whatever the separation", () => {
    for (const sep of [0, 11, 12.7, 1e6]) expect(assignLanes([42], sep)).toEqual([0]);
  });
});

/* The three numbers below are measured off the real page (league
 * 9000000000000000001, owner 900000000000000006, Chrome, `getBoundingClientRect`):
 * the plot's track is 336px at a 390px viewport and 1086px at 1280px, and a
 * label is 42px wide at BOTH — a label is pixels, and pixels do not scale with
 * the track. That is the whole bug.
 *
 * Those two widths are the TRACK — the box a dot's `left: N%` resolves
 * against. They read 364/1114 before the coordinate-space fix, when the ref
 * sat on the padded wrapper instead: 28px wider, and 28px no percentage in
 * this plot can reach. Every assertion below holds under both, which is the
 * point — the function is a ratio, not a calibration. */
const LABEL_PX = 42;
const TRACK_390 = 336;
const TRACK_1280 = 1086;

describe("laneSepPct", () => {
  it("cannot be replaced by any one constant, because the two ends disagree", () => {
    // The old code passed a fixed 11 at every width. 11 is BELOW what a 364px
    // track needs and ABOVE what an 1114px track needs, so no single number
    // serves both — raising it to clear 390px over-separates the desktop.
    expect(laneSepPct(LABEL_PX, TRACK_390)).toBeGreaterThan(11);
    expect(laneSepPct(LABEL_PX, TRACK_1280)).toBeLessThan(11);
  });

  it("separates the real mobile pair the fixed 11 let collide", () => {
    // TE clamps to the axis edge (0) and RB sits at 11.4 on this league's data.
    // 11.4 points of a 364px track is 41px — under the 42px label — and the
    // two boxes overlapped by 22px on the live page. A fixed 11 says [0, 0].
    expect(assignLanes([0, 11.4], laneSepPct(LABEL_PX, TRACK_390))).toEqual([0, 1]);
  });

  it("leaves that same pair on one lane where the track has room", () => {
    // Same data, wider track: 11.4 points is 127px, three label widths of air.
    // A second lane here would spend vertical space for nothing.
    expect(assignLanes([0, 11.4], laneSepPct(LABEL_PX, TRACK_1280))).toEqual([0, 0]);
  });

  it("scales with the track rather than tracking the viewport by accident", () => {
    // Halving the track doubles the percentage the same label costs.
    expect(laneSepPct(LABEL_PX, 500)).toBeCloseTo(2 * laneSepPct(LABEL_PX, 1000), 10);
  });

  it("returns 0 before the container has been measured, never Infinity", () => {
    // First paint / SSR: width 0. Dividing would give Infinity and put every
    // dot on a lane of its own, then collapse them a frame later.
    expect(laneSepPct(LABEL_PX, 0)).toBe(0);
    expect(assignLanes([0, 11.4, 30.2, 30.5], laneSepPct(LABEL_PX, 0))).toEqual([0, 0, 0, 0]);
  });

  it("returns 0 when the labels have not been measured either", () => {
    expect(laneSepPct(0, TRACK_390)).toBe(0);
  });

  it("refuses negative measurements rather than inverting the walk", () => {
    expect(laneSepPct(LABEL_PX, -364)).toBe(0);
    expect(laneSepPct(-42, TRACK_390)).toBe(0);
  });
});

describe("RoomsSection", () => {
  it("plots the OWNER's positions, not a fixed four", () => {
    render(<RoomsSection outlook={outlook(
      { QB: 26, RB: 26.5, WR: 24.5, TE: 27, FB: 29 },
      { QB: 26.8, RB: 25.9, WR: 25.6, TE: 27.4, FB: 28.2 },
    )} />);
    for (const p of ["QB", "RB", "WR", "TE", "FB"]) {
      expect(screen.getByText(p, { exact: false })).toBeTruthy();
    }
  });

  it("does not draw a league key the owner holds none of", () => {
    render(<RoomsSection outlook={outlook(
      { QB: 26 }, { QB: 26.8, RB: 25.9 },
    )} />);
    expect(screen.queryByText(/^RB/)).toBeNull();
  });

  it("renders nothing to compare against when the league map is empty", () => {
    // A pre-feature blob. Absence, not a chart against zero.
    render(<RoomsSection outlook={outlook({ QB: 26 }, {})} />);
    expect(screen.getByText(/league comparison/i)).toBeTruthy();
  });

  it("reads younger as positive from the SIGN of the gap, not absolute age", () => {
    // A 27.0 TE room is young; a 27.0 RB room is old. Both are 27.0.
    const { container } = render(<RoomsSection outlook={outlook(
      { TE: 27.0, RB: 27.0 }, { TE: 27.6, RB: 26.0 },
    )} />);
    const te = container.querySelector('[data-room="TE"] [data-gap]');
    const rb = container.querySelector('[data-room="RB"] [data-gap]');
    expect(te?.className).toContain("text-pos-strong");
    expect(rb?.className).toContain("text-neg-strong");
  });

  it("shows the raw age beneath each dot", () => {
    render(<RoomsSection outlook={outlook({ RB: 26.5 }, { RB: 25.9 })} />);
    expect(screen.getByText("26.5 yr")).toBeTruthy();
  });
});

/* ---------------------------------------------------------------------------
 * ONE COORDINATE SPACE
 *
 * WHAT JSDOM CANNOT DO, STATED PLAINLY: it runs no layout. It resolves no
 * percentage, lays out no CSS Grid, and every `getBoundingClientRect()` here
 * is 0x0 at 0,0. So NONE of these tests can prove a dot lands on a tick or
 * that a ledger stops at its own last row — that evidence is the headless
 * Chrome pass, and only that.
 *
 * What jsdom CAN prove is the structural precondition the browser numbers
 * depend on: that every percentage-positioned element resolves against the
 * SAME containing block as the axis, rather than against a wider padded one.
 * That is the defect, expressed as a fact about the tree. If these fail, the
 * browser numbers cannot be right; if they pass, they still might not be.
 * ------------------------------------------------------------------------ */
describe("rooms plot coordinate space", () => {
  const twoRooms = () => render(<RoomsSection outlook={outlook(
    { TE: 24.5, QB: 26.4 }, { TE: 27.4, QB: 26.8 },
  )} />);

  /** Everything drawn with a percentage `left`, plus the axis hairline. */
  function positioned(container: HTMLElement) {
    const plot = container.querySelector("[data-room]")!.closest("div.relative")!;
    const all = Array.from(plot.querySelectorAll<HTMLElement>("div"));
    return {
      plot,
      axis: all.find((e) => e.className.includes("bg-rule") && e.className.includes("h-px"))!,
      pctLeft: all.filter((e) => (e.style.left || "").endsWith("%")),
    };
  }

  it("resolves the axis and every percentage against ONE containing block", () => {
    // THE BUG: the axis was `inset-x-3.5` on the padded wrapper while the
    // dots, stems, labels and ticks used `left: N%`, which resolves against
    // the PADDING box — 14px wider on each side. Measured live at 1280px
    // before the fix: the ±2 ticks drew at 83.5 / 1197.5 against an axis
    // running 97→1183.
    //
    // A shared parent alone does NOT say this: in the broken tree the axis and
    // every percentage were already siblings, and this test passed on it. What
    // separates the two shapes is that the axis was POSITIVELY INSET from the
    // box those percentages resolve against, so 0% and the line's left end
    // were 14px apart. Assert both halves: same parent, and no positive
    // horizontal inset against it.
    const { container } = twoRooms();
    const { axis, pctLeft } = positioned(container);
    expect(pctLeft.length).toBeGreaterThan(4); // 4 ticks + zero + per-room dot/label
    for (const el of pctLeft) expect(el.parentElement).toBe(axis.parentElement);

    expect(axis.className).not.toMatch(/\b(inset-x|left|right)-(?!0\b)[\w.[\]/-]+/);
    for (const edge of [axis.style.left, axis.style.right]) {
      expect(parseFloat(edge || "0")).toBeLessThanOrEqual(0);
    }
  });

  it("gives that containing block the axis's own span, not the padded box", () => {
    const { container } = twoRooms();
    const { plot, axis } = positioned(container);
    const track = axis.parentElement!;
    expect(track).not.toBe(plot);              // the padded wrapper is NOT the space
    expect(plot.className).toContain("px-3.5"); // the padding is kept
    expect(track.className).toContain("inset-x-3.5"); // ...and the track clears it
    expect(track.className).toContain("inset-y-0");   // vertical space is untouched
  });

  it("measures the track, not the padded wrapper", () => {
    // `laneSepPct` divides a label's PIXELS by the track's PIXELS. Reading the
    // 28px-wider wrapper understates every separation by ~8%, which is lanes
    // the collision walk does not open.
    const { container } = twoRooms();
    const { plot, axis } = positioned(container);
    // The ref lives on the track. jsdom cannot read a ref, but the element the
    // ResizeObserver observes is the one holding the labels, so assert that.
    const label = container.querySelector("[data-room]")!;
    expect(label.parentElement).toBe(axis.parentElement);
    expect(label.parentElement).not.toBe(plot);
  });

  it("draws the hairline half a dot longer than the track at each end", () => {
    // Otherwise an edge-clamped dot — CENTRED on 0% — always pokes out of the
    // end of its own axis. The line gives way by the radius; the dot does not
    // move, because moving it would take it off the −2yr tick.
    const { container } = twoRooms();
    const { axis } = positioned(container);
    expect(axis.style.left).toBe("-3.5px");
    expect(axis.style.right).toBe("-3.5px");
  });
});

describe("labelAnchorPx", () => {
  /* THE TRACK AND LABEL WIDTHS ARE THE LIVE ONES. Chrome,
   * getBoundingClientRect, league 9000000000000000001 / owner
   * 900000000000000006: the track measures 336 / 622 / 1086px at 390 / 700 /
   * 1280, and every rendered label is 42.3px wide at all three.
   *
   * The near-edge cases below are SYNTHETIC on purpose. No room in any warm
   * league sits at pct 3 or 97 — which is exactly why a binary anchor could
   * ship broken and stay invisible until it landed on a stranger's roster.
   * jsdom cannot lay this out, so the containment is asserted against the
   * function that decides it, at the widths the browser actually reports. */
  const LIVE: Array<[string, number]> = [["390", 336], ["700", 622], ["1280", 1086]];
  const W = 42.3;

  function box(pct: number, track: number) {
    const c = labelAnchorPx(pct, track, W)!;
    return { left: c - W / 2, right: c + W / 2, centre: c };
  }

  it.each(LIVE)("keeps a near-LEFT-edge label inside the %spx track", (_v, track) => {
    // pct 3 centres the label 3% along: 10.1px on a 336px track, so a centred
    // 42.3px label would run -11.1 → 31.2 and be cut by Panel's
    // overflow-hidden. The old switch did NOT fire here: it only moved at
    // pct <= 0.
    const b = box(3, track);
    expect(b.left).toBeGreaterThanOrEqual(0);
    expect(b.right).toBeLessThanOrEqual(track);
  });

  it.each(LIVE)("keeps a near-RIGHT-edge label inside the %spx track", (_v, track) => {
    const b = box(97, track);
    expect(b.left).toBeGreaterThanOrEqual(0);
    expect(b.right).toBeLessThanOrEqual(track);
  });

  it.each(LIVE)("keeps EVERY position inside the %spx track, not just the ends", (_v, track) => {
    // The constraint is continuous, so the test sweeps rather than sampling
    // the two extremes the old code happened to handle.
    for (let pct = -10; pct <= 110; pct += 0.5) {
      const b = box(pct, track);
      expect(b.left).toBeGreaterThanOrEqual(0);
      expect(b.right).toBeLessThanOrEqual(track);
    }
  });

  it("agrees with the retired switch at both endpoints", () => {
    // pct 0 puts the label's LEFT edge on the track start (the old
    // translateX(0%)); pct 100 puts its RIGHT edge on the track end (the old
    // translateX(-100%)). The extremes are unchanged; the ground between them
    // is now covered instead of jumping.
    expect(box(0, 336).left).toBeCloseTo(0, 10);
    expect(box(100, 336).right).toBeCloseTo(336, 10);
  });

  it("leaves a mid-track label centred on its dot", () => {
    // A clamp must not move a label that was never in danger — the label
    // belongs under its dot wherever it can be.
    expect(labelAnchorPx(50, 336, W)).toBeCloseTo(168, 10);
    expect(labelAnchorPx(26.5, 1086, W)).toBeCloseTo(287.79, 2);
  });

  it("is monotonic, so a room further right never draws further left", () => {
    let prev = -Infinity;
    for (let pct = 0; pct <= 100; pct += 1) {
      const c = labelAnchorPx(pct, 336, W)!;
      expect(c).toBeGreaterThanOrEqual(prev);
      prev = c;
    }
  });

  it("returns null before the track and labels have been measured", () => {
    // SSR / first paint. A clamp against 0 would collapse every label onto
    // x=0; the caller falls back to centring on the pct instead.
    expect(labelAnchorPx(50, 0, W)).toBeNull();
    expect(labelAnchorPx(50, 336, 0)).toBeNull();
    expect(labelAnchorPx(50, -336, W)).toBeNull();
    expect(labelAnchorPx(50, 336, -42)).toBeNull();
  });

  it("centres a label wider than the whole track rather than picking a side", () => {
    // Unreachable at any real width, but the clamp inverts here (half >
    // track - half) and Math.min/Math.max would otherwise pin it to one edge
    // and dump the entire overflow on the other.
    expect(labelAnchorPx(0, 30, 42.3)).toBeCloseTo(15, 10);
    expect(labelAnchorPx(100, 30, 42.3)).toBeCloseTo(15, 10);
  });
});

describe("edge-clamped anchoring", () => {
  function labelFor(container: HTMLElement, pos: string) {
    return container.querySelector<HTMLElement>(`[data-room="${pos}"]`)!;
  }

  /* jsdom reports every width as 0, so `labelAnchorPx` returns null and these
   * render the PRE-MEASURE paint: centred on the pct. That is the fallback
   * being asserted, not the clamp — the clamp is covered above, against live
   * widths, and in the browser. */
  it("clamps a beyond-axis room to the track end and still states the true gap", () => {
    // TE 2.9 years younger than the league TE room — past the ±2yr clamp.
    const { container } = render(<RoomsSection outlook={outlook(
      { TE: 24.5, QB: 26.4 }, { TE: 27.4, QB: 26.8 },
    )} />);
    const te = labelFor(container, "TE");
    expect(te.style.left).toBe("0%");
    expect(te.textContent).toContain("\u22122.9");
  });

  it("clamps a beyond-axis room at the other end too", () => {
    const { container } = render(<RoomsSection outlook={outlook(
      { RB: 28.9, QB: 26.4 }, { RB: 26.0, QB: 26.8 },
    )} />);
    const rb = labelFor(container, "RB");
    expect(rb.style.left).toBe("100%");
    expect(rb.textContent).toContain("+2.9");
  });

  it("gives every label ONE transform, since the anchor is now a position", () => {
    // The retired code chose between translateX(0%), (-50%) and (-100%). The
    // shift lives in `left` now, so the transform is invariant — that is what
    // makes the anchor continuous instead of three-valued.
    const { container } = render(<RoomsSection outlook={outlook(
      { TE: 24.5, QB: 26.4, WR: 25.0, RB: 28.9 },
      { TE: 27.4, QB: 26.8, WR: 25.6, RB: 26.0 },
    )} />);
    for (const pos of ["TE", "QB", "WR", "RB"]) {
      expect(labelFor(container, pos).style.transform).toBe("translateX(-50%)");
    }
  });

  it("puts the dot on the clamp, never nudged inward off its tick", () => {
    const { container } = render(<RoomsSection outlook={outlook(
      { TE: 24.5, RB: 28.9 }, { TE: 27.4, RB: 26.0 },
    )} />);
    const plot = container.querySelector("[data-room]")!.closest("div.relative")!;
    const dotWraps = Array.from(plot.querySelectorAll<HTMLElement>("div.-translate-x-1\\/2"));
    const lefts = dotWraps.map((d) => d.style.left).sort();
    expect(lefts).toEqual(["0%", "100%"]);
  });
});

describe("young core / aging risks ledgers", () => {
  it("lets each ledger take its own height instead of the taller one's", () => {
    // Grid's default `align-items: stretch` sized both columns to the tallest
    // row: measured live at 1280px, young core 15 rows at 602px and aging
    // risks 1 row ALSO at 602px — one entry over ~560px of blank panel.
    //
    // jsdom lays out no grid, so it cannot measure that. What it can hold is
    // the class that decides it.
    const { container } = render(<RoomsSection outlook={outlook(
      { QB: 26 }, { QB: 26.8 },
    )} />);
    const grid = container.querySelector<HTMLElement>(".grid")!;
    expect(grid.className).toContain("sm:grid-cols-2");
    expect(grid.className).toContain("items-start");
  });
});
