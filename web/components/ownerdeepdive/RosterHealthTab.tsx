"use client";

import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { OutlookView, PlayerLite } from "@/lib/types";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { SectionHeader, useSectionCollapse } from "../furniture/SectionCollapse";
import { Card, CardHead } from "./ui";

/* ---------------------------------------------------------------------------
 * §4 "Your rooms vs the league" — a dot plot on a RELATIVE axis, zero = that
 * position's league average.
 *
 * An absolute age axis cannot carry a verdict: a 27.0 TE room is young and a
 * 27.0 RB room is old, so every dot would need a different reference. The
 * absolute version with unlabelled league-average ticks was built and
 * rejected — the ticks could not be attributed to their dots. Left of centre
 * IS the verdict here; raw age rides beneath each dot.
 * ------------------------------------------------------------------------ */

/** Half-width of the axis in years. Beyond it a dot clamps to the edge; the
 *  label still states the true gap. */
const AXIS_YEARS = 2;

/** Air between two labels that sit side by side in one lane, in px. Two boxes
 *  that merely touch read as one blob, so the bar is a label width plus a
 *  little. */
const LABEL_AIR_PX = 4;

/**
 * The minimum separation the collision walk needs, in percentage points of the
 * track, from the two things that actually decide it: how wide a label is and
 * how wide the track is. Both are pixels; the walk speaks percent.
 *
 * This used to be a fixed 11 points, and a fixed percentage CANNOT be right,
 * because the quantity it stands in for does not scale with the track. A label
 * is ~42px whatever the viewport. 11 points is 119px of a 1086px desktop track
 * (over-separating, spending lanes and vertical space where there is room) and
 * only 37px of a 336px mobile track — under the label width, which is how two
 * labels landed in one lane overlapping by 22px on a real league at 390px while
 * every tested desktop width stayed clean. Raising the constant to a number
 * that clears 390px only moves the same bug to whatever width nobody measured.
 *
 * (Those two track widths are the AXIS's own span, measured after the
 * coordinate-space fix. They were read as 364px / 1114px when the ref sat on
 * the padded wrapper — 28px of padding wider, and 28px that no percentage
 * here has ever been able to reach.)
 *
 * Degenerate inputs return 0 — one lane, which is exactly what the pre-measure
 * paint already is — rather than dividing by zero into Infinity and putting
 * every dot on a lane of its own.
 */
export function laneSepPct(labelPx: number, trackPx: number): number {
  if (!(trackPx > 0) || !(labelPx > 0)) return 0;
  return ((labelPx + LABEL_AIR_PX) / trackPx) * 100;
}

/** `useLayoutEffect` on the client so the measured lanes land before paint;
 *  `useEffect` on the server, where the layout variant only warns. */
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * Measure the TRACK's own box and its widest rendered label.
 *
 * The ref goes on the track element (see `RoomsSection`), not on the padded
 * plot wrapper. Those are different widths — 336px vs 364px at a 390px
 * viewport — and the percentage the collision walk speaks is a percentage OF
 * THE TRACK, because that is what a dot's `left: N%` now resolves against.
 * Measuring the padded wrapper made every separation ~8% too small.
 *
 * The labels are MEASURED rather than assumed at a constant: their width moves
 * with the webfont (a fallback face is live until Bricolage/the mono face
 * swaps in) and with content (`FB +12.3` is wider than `TE −2.1`), and a
 * hardcoded number would be right only for the string that was measured, in
 * the face that was loaded, on the day it was measured.
 *
 * Lane assignment does not feed back into label width — a label's width is its
 * content, not its position — so reading the labels after render converges
 * rather than oscillating; the setState bails on an unchanged pair.
 */
function usePlotMetrics() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [metrics, setMetrics] = useState({ trackPx: 0, labelPx: 0 });

  // No dependency array on purpose: the label set and its text change with the
  // data, and every render must re-read them. The bail-out below is what stops
  // that from looping.
  useIsoLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const labels = () => Array.from(el.querySelectorAll<HTMLElement>("[data-room]"));
    const read = () => {
      const trackPx = el.getBoundingClientRect().width;
      const labelPx = labels().reduce((w, l) => Math.max(w, l.getBoundingClientRect().width), 0);
      setMetrics((prev) =>
        prev.trackPx === trackPx && prev.labelPx === labelPx ? prev : { trackPx, labelPx },
      );
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    for (const l of labels()) ro.observe(l);
    return () => ro.disconnect();
  });

  return [ref, metrics] as const;
}

/** Vertical step per collision lane.
 *
 *  Measured, not guessed: a live Chrome render of the two-line label
 *  (`text-label`, 8.5px / 12.75px line-height) put its "POS ±G" line and its
 *  "NN.N yr" line at a combined 25.5px tall (getBoundingClientRect on both
 *  lines, 390px viewport). The step between two lanes must be at least that
 *  tall, or the next lane's label starts before the previous one's label
 *  ends — measured at the old 18px step: WR/TE shared x=80, y=1263, heights
 *  45/63, an ~8px overlap. 28px clears the measured 25.5px with ~2.5px of
 *  air rather than landing exactly on the boundary. */
const LANE_STEP_PX = 28;
const STEM_BASE_PX = 12;

/** Dot diameter. One constant because two things need it: the dot itself, and
 *  the axis hairline, which is drawn HALF A DOT LONGER at each end than the
 *  track it labels.
 *
 *  That overhang is the only way an edge-clamped dot can be both on its tick
 *  and inside the line. A dot at `left: 0%` is CENTRED on the track's start,
 *  so its box necessarily reaches half a dot further left; if the line stopped
 *  there, the extreme dot — the one the reader most needs to trust — would
 *  always poke out of the end of its own axis. Nudging the dot inward instead
 *  would take it off the −2yr tick and quietly misplace the one value the
 *  clamp exists to state. So the LINE gives way, by exactly the radius: the
 *  axis caps the extreme dots rather than being pierced by them. */
const DOT_PX = 7;

/**
 * Where a room's LABEL is centred, in px from the track's left edge — the dot's
 * own position, pulled back just far enough that the label box stays inside the
 * track. Returns `null` before the track and the labels have been measured.
 *
 * WHY A CLAMP AND NOT A SWITCH. This replaced a three-value `labelShift` that
 * anchored left at exactly `pct <= 0`, right at exactly `pct >= 100`, and
 * centred everywhere else. Clipping is not a property of the two endpoints —
 * it starts the moment half a label passes the edge, which is `labelPx / 2`
 * short of it. On a 336px track a ~42px label is already 21px, i.e. 6.25
 * percentage points, so every room between pct 0 and 6.25 (and 93.75 to 100)
 * centred its label across the boundary and was cut by `Panel`'s
 * `overflow-hidden` — a symptom visually identical to the coordinate-space bug
 * this file just fixed, and one that no room in any warm league happens to sit
 * at. A binary anchor cannot express a continuous constraint; a clamp can.
 *
 * It AGREES with the old switch at the two endpoints — pct 0 lands the label's
 * left edge on the track's start, pct 100 its right edge on the track's end —
 * so the extremes look exactly as they did, and the ground between them is
 * covered rather than jumping.
 *
 * Only the LABEL moves. The dot stays on its clamp, because the dot's position
 * IS the reading.
 *
 * `labelPx` is the widest label on the plot, not this one's own width, so the
 * clamp is conservative: a narrower label lands a little further inside than it
 * strictly had to, never outside. That is the safe direction, and it is why the
 * element keeps a plain `translateX(-50%)` against its OWN width.
 *
 * A label wider than the whole track cannot be contained at all; centring it
 * spills evenly on both sides rather than dumping the whole overflow on one.
 */
export function labelAnchorPx(
  pct: number, trackPx: number, labelPx: number,
): number | null {
  if (!(trackPx > 0) || !(labelPx > 0)) return null;
  if (labelPx >= trackPx) return trackPx / 2;
  const half = labelPx / 2;
  return Math.min(Math.max((pct / 100) * trackPx, half), trackPx - half);
}

/**
 * Assign each dot (given as its position along the track, 0-100) to the
 * lowest lane whose last-placed label is at least `minSepPct` away.
 *
 * Label collision here is real, not cosmetic: rooms collide whenever two sit
 * within ~0.3 years, and hand-placing passes on one league's data and breaks
 * on the next. Lanes grow as needed rather than capping at two — three rooms
 * inside one label width is an ordinary roster, not a pathological one.
 *
 * `pcts` need not be sorted; lanes are assigned in left-to-right order and
 * returned in the caller's original order.
 */
export function assignLanes(pcts: number[], minSepPct: number): number[] {
  const order = pcts.map((p, i) => ({ p, i })).sort((a, b) => a.p - b.p);
  const lastInLane: number[] = [];
  const lanes = new Array<number>(pcts.length);
  for (const { p, i } of order) {
    let lane = 0;
    while (lane < lastInLane.length && p - lastInLane[lane] < minSepPct) lane += 1;
    lastInLane[lane] = p;
    lanes[i] = lane;
  }
  return lanes;
}

/** Younger reads as positive, from the SIGN of the gap alone.
 *
 *  This is a NEW helper on purpose. The old `ageTextTone` thresholded on
 *  ABSOLUTE age (>=27 negative, <=24.5 positive), which is exactly what a
 *  relative axis exists to replace. The stance is not universally true — a
 *  room can be too young to produce now — and that is accepted: the sign alone
 *  is the alternative.
 *
 *  Tone lands on the FIGURE, never on the dot. Colour never carries
 *  information that is not also in the figure. */
function gapTone(gap: number): string {
  if (gap < 0) return "text-pos-strong";
  if (gap > 0) return "text-neg-strong";
  return "text-dim";
}

function fmtGap(gap: number): string {
  return `${gap > 0 ? "+" : gap < 0 ? "−" : "±"}${Math.abs(gap).toFixed(1)}`;
}

export function RoomsSection({ outlook }: { outlook: OutlookView }) {
  const ap = outlook.age_profile;
  const league = ap.league_avg_age_by_position ?? {};
  // `SectionCollapse` exports a HOOK plus a `SectionHeader`, not a wrapper
  // component — same shape TradeProductionCard.tsx and TradeScoreboard.tsx use.
  const roster = useSectionCollapse("outlook-roster");
  // Called before the empty-state return below: hooks run unconditionally.
  const [plotRef, plot] = usePlotMetrics();

  // The owner's OWN keys, intersected with the league map. The position set is
  // not fixed at four: an FB yields a fifth key, and a position the owner
  // holds none of yields no key at all (dynasty.py builds
  // avg_age_by_position from whatever non-K/DEF positions the roster carries).
  // A league key with no owner dot is simply not drawn.
  const rooms = Object.entries(ap.avg_age_by_position)
    .filter(([pos]) => league[pos] != null)
    .map(([pos, age]) => ({ pos, age, gap: age - league[pos] }))
    .sort((a, b) => a.gap - b.gap);

  if (rooms.length === 0) {
    return (
      <Card>
        <CardHead title="Your rooms vs the league" />
        <p className="text-figure leading-snug text-dim">
          A league comparison lands here on the next refresh.
        </p>
      </Card>
    );
  }

  const pcts = rooms.map(
    (r) => 50 + (Math.max(-AXIS_YEARS, Math.min(AXIS_YEARS, r.gap)) / AXIS_YEARS) * 50,
  );
  const lanes = assignLanes(pcts, laneSepPct(plot.labelPx, plot.trackPx));
  const laneCount = Math.max(...lanes) + 1;

  return (
    <Card>
      <CardHead title="Your rooms vs the league" />
      <Panel>
        <div className="relative px-3.5 py-5" style={{ minHeight: 76 + laneCount * LANE_STEP_PX }}>
          {/* THE TRACK — the plot's horizontal coordinate space, and the ONLY
              one. Everything drawn in the plot — hairline, zero line, ticks,
              dots, stems, labels — is positioned against this box, so
              `left: 0%` is the −2yr end for all of them and `left: 100%` the
              +2yr end. (The hairline alone is drawn a dot-radius longer at
              each end, so it caps the extreme dots; see DOT_PX.)

              This element exists because it is the fix for a real defect: the
              axis used to be `inset-x-3.5` on the padded wrapper while every
              dot, stem, label and tick used `left: N%`. A percentage `left`
              resolves against the containing block's PADDING box — the padding
              included — so the two systems disagreed by the 14px pad on each
              side. Measured live at 1280px: the ±2 ticks drew at x=83.5 and
              x=1197.5 against an axis running 97→1183, i.e. 13.5px and 14.5px
              adrift, the error zero at centre and worst at the ends; and the
              −2yr-clamped dot's box ran 79.5→86.5, entirely outside the axis
              and past the panel's inner edge, where `overflow-hidden` sliced
              it in half. Mixing `inset-x-*` with percentages of a padded
              parent cannot be made to agree — one track is the fix.

              `inset-y-0` on purpose: the track only redefines the HORIZONTAL
              space, so every `top-*` below keeps meaning what it meant. */}
          <div ref={plotRef} className="absolute inset-x-3.5 inset-y-0">
            {/* The axis: a --rule hairline with a --rule-strong zero line.
                It runs half a dot past the track at each end — see DOT_PX. */}
            <div
              className="absolute top-5 h-px bg-rule"
              style={{ left: -DOT_PX / 2, right: -DOT_PX / 2 }}
            />
            <div className="absolute top-3 h-[18px] w-px bg-rule-strong" style={{ left: "50%" }} />
            {[-2, -1, 1, 2].map((t) => (
              <div
                key={t}
                className="absolute top-4 h-[7px] w-px bg-rule"
                style={{ left: `${50 + (t / AXIS_YEARS) * 50}%` }}
              />
            ))}
            {rooms.map((r, i) => {
              const pct = pcts[i];
              const stemHeight = STEM_BASE_PX + lanes[i] * LANE_STEP_PX;
              /* An edge-clamped dot (gap beyond the +/-2yr axis) sits on the
               * END OF THE AXIS, which is 14px inside the panel's inner edge.
               * Its own 7px box therefore clears that edge with room to spare
               * — the earlier note here accepted "a few px past the edge" for
               * the half-dot, and that reasoning is SUPERSEDED: the dot used to
               * land 14px further out than the axis end (the coordinate-space
               * bug above), so the overhang was never ~3.5px, it was 17.5px and
               * the panel clipped the dot in half. Nothing overhangs now.
               *
               * The LABEL still has to be pulled in, and it is CLAMPED rather
               * than switched — see `labelAnchorPx`. `null` is the pre-measure
               * paint (SSR, first frame): fall back to centring on the pct, the
               * same "no measurement yet, do the plain thing" the lane walk
               * does when `laneSepPct` returns 0. */
              const anchor = labelAnchorPx(pct, plot.trackPx, plot.labelPx);
              return (
                // No wrapping element around both children on purpose: a plain
                // (non-positioned) div holding only `absolute` descendants
                // collapses to a zero-size box (abs-positioned children don't
                // contribute to a static-position ancestor's flow size), which
                // is invisible to any layout measurement — including the
                // live-browser check this fix exists to satisfy. `data-room`
                // lives on the label div instead: it is the one still-sized
                // element, and `[data-room="X"] [data-gap]` still matches since
                // `data-gap` is its own descendant.
                <Fragment key={r.pos}>
                  {/* Dot + stem: always centred on the clamp position. */}
                  <div className="absolute -translate-x-1/2" style={{ left: `${pct}%`, top: 12 }}>
                    <span
                      className="mx-auto block rounded-pill bg-ink"
                      style={{ width: DOT_PX, height: DOT_PX }}
                    />
                    <span className="mx-auto block w-px bg-rule" style={{ height: stemHeight }} />
                  </div>
                  {/* Label: positioned independently so an edge dot's label can
                      anchor away from centre instead of overflowing. */}
                  <div
                    data-room={r.pos}
                    className="absolute whitespace-nowrap text-center"
                    style={{
                    left: anchor ?? `${pct}%`,
                    top: 12 + DOT_PX + stemHeight,
                    transform: "translateX(-50%)",
                  }}
                  >
                    <span className="block font-mono text-label uppercase tracking-[0.11em] text-dim">
                      {r.pos}{" "}
                      <span data-gap className={`tabular ${gapTone(r.gap)}`}>{fmtGap(r.gap)}</span>
                    </span>
                    <span className="block font-mono text-label tabular text-dim">
                      {r.age.toFixed(1)} yr
                    </span>
                  </div>
                </Fragment>
              );
            })}
          </div>
        </div>
      </Panel>
      <p className="mt-2 max-w-[68ch] text-figure leading-snug text-dim">
        Zero is that position&rsquo;s league average, so left of centre is a younger room
        than the league&rsquo;s. Raw age sits beneath each dot.
      </p>

      <SectionHeader
        title="Young core and aging risks"
        open={roster.open}
        onToggle={roster.toggle}
      />
      {roster.open && (
        /* `items-start` is load-bearing, not tidiness. Grid's default
           `align-items: stretch` sizes every item to the tallest row, so the
           two ledgers are ALWAYS the same height however many rows each holds
           — measured live at 1280px: young core 15 rows at 602px, aging risks
           1 row also at 602px, i.e. one entry over ~560px of blank panel.
           Each ledger is its own list and takes its own height. */
        <div className="mt-2 grid grid-cols-1 items-start gap-x-6 sm:grid-cols-2">
          <PlayerLedger players={[...ap.core_young].sort((a, b) => (a.age ?? 99) - (b.age ?? 99))} />
          <PlayerLedger players={[...ap.aging_risks].sort((a, b) => (b.age ?? 0) - (a.age ?? 0))} />
        </div>
      )}
    </Card>
  );
}

function PlayerLedger({ players }: { players: PlayerLite[] }) {
  if (players.length === 0) {
    return (
      <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">
        None on record
      </div>
    );
  }
  return (
    <Panel>
      {players.map((p) => (
        <Row key={p.player_id} className="grid-cols-[minmax(0,1fr)_34px_34px] items-center gap-2">
          <span className="min-w-0 truncate font-display text-figure font-bold tracking-[-0.02em]">
            {p.full_name}
          </span>
          <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">{p.position}</span>
          <span className="text-right font-mono text-figure tabular text-dim">
            {p.age != null ? p.age : "—"}
          </span>
        </Row>
      ))}
    </Panel>
  );
}
