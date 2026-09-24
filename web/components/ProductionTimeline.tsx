"use client";

import { useState } from "react";
import type { ProductionMetric, ProductionPoint } from "../lib/types";
import { SegmentControl } from "./SegmentControl";

/* ---------------------------------------------------------------------------
 * Production plot — Furniture identity strokes, with heavier weight for the
 * metric's winner. Both sides share a zero-based scale fitted to visible data.
 *   - No legend. Each line is labelled at its own right end with the owner
 *     and final figure in the right gutter. Nearby labels separate vertically
 *     and connect back to their endpoints. Mobile labels stack above the plot
 *     instead (still naming the stroke via a mini swatch, still no key).
 *   - The phase rail (one 26px rule under the axis, solid ink for postseason
 *     weeks, empty for regular) replaces the old amber playoff band AND the
 *     per-side injury tints — injury context still lives in the page's own
 *     Injury Impact block, just not painted onto the chart.
 *   - Plot height starts at five 26px rules on desktop, three on mobile,
 *     and grows to fit extra labels. Tick intervals use readable steps, with
 *     headroom above the peak rather than a fixed minimum point range.
 * ------------------------------------------------------------------------ */

/** The identity STROKE ramp, by series position. Six values, and a plot never
 *  shows more than two sides, so the modulo is a guard rather than a real case.
 *  Never `--id-1..6` here: those are fills. */
function seriesStroke(i: number): string {
  return `var(--id-${(i % 6) + 1}-line)`;
}

export interface TimelineLine {
  key: string;
  label: string;
  byMetric: Record<ProductionMetric, ProductionPoint[]>;
  departures?: { season: number; week: number; label: string; kind: "dropped" | "traded" }[];
}

/* ORDER: Total leads because it is the first of the five-metric taxonomy's
 * production metrics (CLAUDE.md's fixed order — Total Points · Regular Season ·
 * Playoff · Toilet Bowl), so the run reads as that vocabulary with "Started"
 * inserted rather than as its own arrangement. Started sits second, not first,
 * despite being the DEFAULT view: the default is about which question the chart
 * opens on, the order is about which vocabulary the labels belong to, and those
 * are two different jobs. */
const METRICS: ProductionMetric[] = ["total", "started", "regular", "playoff", "toilet"];
// Short forms — same abbreviations TradeStatTable/TradeScoreboard use
// (lib/trade-lens.ts LENS_LABEL) so "Reg" reads the same everywhere on the
// trade page. "started" has no counterpart in the five-metric taxonomy (it's
// starters-only points summed across every phase, a byproduct of the
// engine's METRIC_GATES, not net_ktc/Trade Value) — it keeps an honest label
// rather than being mislabelled "Value": no per-week Trade Value series
// exists to chart (see report).
const METRIC_LABEL: Record<ProductionMetric, string> = {
  started: "Started", total: "Total", regular: "Reg", playoff: "Playoff", toilet: "Toilet",
};

const MONO = "var(--font-geist-mono), ui-monospace, monospace";
/* The display face, as an inline SVG font stack — `font-display` is a Tailwind
 * class and this is an SVG `fontFamily` attribute, so the stack is spelled out.
 * Mirror of `tailwind.config.ts`'s `fontFamily.display`: the `next/font/local`
 * variable first, the design system's real family name behind it for
 * latin-ext. `--font-archivo` no longer exists — Archivo is dropped. */
const DISPLAY = "var(--font-bricolage), 'Bricolage Grotesque', system-ui, sans-serif";

// Geometry per breakpoint. Desktop reserves a right gutter for the
// end-of-line labels; mobile has none (labels stack above the plot instead).
const GEOM = {
  desktop: { w: 1080, padL: 46, padR: 118, padT: 18, rules: 5 },
  mobile: { w: 360, padL: 40, padR: 14, padT: 20, rules: 3 },
} as const;
type Variant = keyof typeof GEOM;
const RULE = 26; // --rule-pitch, mirrored here since SVG can't read the token.

function measureStep(max: number, rules: number): number {
  if (max <= 0) return 1;
  const target = (max * 1.1) / rules;
  const magnitude = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 2.5, 5, 10].find((factor) => factor * magnitude >= target)!;
  return step * magnitude;
}

function fmtFigure(v: number): string {
  return v.toFixed(1);
}

export function ProductionTimeline({
  axis, lines, defaultMetric = "started", metric: metricProp, onMetricChange, weekPhases,
  leading,
}: {
  axis: [number, number][];
  lines: TimelineLine[];
  defaultMetric?: ProductionMetric;
  metric?: ProductionMetric;
  onMetricChange?: (m: ProductionMetric) => void;
  weekPhases?: string[];
  /** A second filter run to share the metric run's line, split by a hairline
   *  — the owner page's Both/Got/Gave. It rides here rather than in the
   *  parent because two filter rows stacked is the 120px this redesign was
   *  about: the saving is the shared LINE, not the shorter control. */
  leading?: React.ReactNode;
}) {
  const [internalMetric, setInternalMetric] = useState<ProductionMetric>(defaultMetric);
  const metric = metricProp ?? internalMetric;
  const setMetric = (m: ProductionMetric) => {
    if (onMetricChange) { onMetricChange(m); } else { setInternalMetric(m); }
  };

  const series = lines.map((l) => ({ ...l, pts: l.byMetric[metric] || [] }));

  // Trim the flat pre-trade run-up so the climb starts at the left edge (trade).
  const firstNonZero = Math.min(
    ...series.map((s) => {
      const i = s.pts.findIndex((p) => p.value > 0);
      return i < 0 ? Infinity : i;
    }),
  );
  const hasData = Number.isFinite(firstNonZero);
  const startIdx = hasData ? Math.max(0, (firstNonZero as number) - 1) : 0;
  const tAxis = axis.slice(startIdx);
  const tSeries = series.map((s) => ({ ...s, pts: s.pts.slice(startIdx) }));
  const n = tAxis.length;

  const max = Math.max(...tSeries.flatMap((s) => s.pts.map((p) => p.value)), 0);

  // The winner's line is heavier. A solo line in the owner's Got/Gave view
  // receives the same emphasis.
  const finalValue = (pts: ProductionPoint[]) => (pts.length ? pts[pts.length - 1].value : 0);
  const winnerKey = tSeries.length === 0 ? undefined
    : tSeries.length === 1 ? tSeries[0].key
      : tSeries.reduce((best, s) => (finalValue(s.pts) > finalValue(best.pts) ? s : best), tSeries[0]).key;

  const boundaries: number[] = [];
  tAxis.forEach(([s], i) => { if (i > 0 && s !== tAxis[i - 1][0]) boundaries.push(i); });

  const tPhases = weekPhases ? weekPhases.slice(startIdx) : [];
  const postIdx = new Set(tPhases.map((p, i) => (p === "post" ? i : -1)).filter((i) => i >= 0));

  function phaseSegments(x: (i: number) => number, padL: number, plotRight: number) {
    if (n === 0) return [] as { x0: number; x1: number; post: boolean }[];
    const bound = (i: number) => (i <= 0 ? padL : i >= n ? plotRight : (x(i - 1) + x(i)) / 2);
    const segs: { i0: number; i1: number; post: boolean }[] = [];
    let curPost = postIdx.has(0);
    let start = 0;
    for (let i = 1; i < n; i++) {
      const isPost = postIdx.has(i);
      if (isPost !== curPost) {
        segs.push({ i0: start, i1: i - 1, post: curPost });
        start = i; curPost = isPost;
      }
    }
    segs.push({ i0: start, i1: n - 1, post: curPost });
    return segs.map((s) => ({ x0: bound(s.i0), x1: bound(s.i1 + 1), post: s.post }));
  }

  // Desktop adaptive x-ticks: the trade origin, every season boundary, the
  // end, and interior weeks for short (<=2 season) spans — filtered so
  // collinear labels never overlap. Mobile drops interior ticks entirely and
  // keeps just the trade origin and the end (DESIGN.md § Responsive: Charts).
  function desktopTicks(x: (i: number) => number) {
    const seasonCount = new Set(tAxis.map((a) => a[0])).size;
    const PRIORITY: Record<string, number> = { trade: 3, boundary: 3, end: 2, week: 1 };
    const cands: { i: number; kind: string }[] = [{ i: 0, kind: "trade" }];
    boundaries.forEach((b) => cands.push({ i: b, kind: "boundary" }));
    if (n > 1) cands.push({ i: n - 1, kind: "end" });
    if (seasonCount <= 2 && n > 6) {
      const step = Math.max(1, Math.round((n - 1) / 6));
      for (let i = step; i < n - 1; i += step) cands.push({ i, kind: "week" });
    }
    const byIdx = new Map<number, { i: number; kind: string }>();
    for (const c of cands) {
      const ex = byIdx.get(c.i);
      if (!ex || PRIORITY[c.kind] > PRIORITY[ex.kind]) byIdx.set(c.i, c);
    }
    const MINGAP = 90;
    const out: { i: number; kind: string }[] = [];
    for (const c of [...byIdx.values()].sort((a, b) => a.i - b.i)) {
      const last = out[out.length - 1];
      if (!last || x(c.i) - x(last.i) >= MINGAP) out.push(c);
      else if (PRIORITY[c.kind] > PRIORITY[last.kind]) out[out.length - 1] = c;
    }
    return out;
  }
  const mobileTicks = () => (n > 1 ? [{ i: 0, kind: "trade" }, { i: n - 1, kind: "end" }] : [{ i: 0, kind: "trade" }]);

  function renderPlot(variant: Variant) {
    const g = GEOM[variant];
    const plotW = g.w - g.padL - g.padR;
    const labelGap = 32;
    const plotH = Math.max(RULE * g.rules, variant === "desktop" ? (tSeries.length - 1) * labelGap + 24 : 0);
    const baselineY = g.padT + plotH;
    const railY = baselineY + 24;
    const railH = 17;
    const H = railY + railH + 9;
    const plotRight = g.w - g.padR;

    const x = (i: number) => (n <= 1 ? g.padL : g.padL + (i / (n - 1)) * plotW);
    const step = measureStep(max, g.rules);
    const topVal = step * g.rules;
    const y = (v: number) => g.padT + plotH - (topVal > 0 ? (v / topVal) * plotH : 0);
    const measures = Array.from({ length: g.rules + 1 }, (_, k) => Number(((g.rules - k) * step).toPrecision(12)));
    const tickDigits = Math.min(20, Math.max(0, 1 - Math.floor(Math.log10(step))));
    const path = (pts: ProductionPoint[]) => pts.map((p, i) => `${x(i)},${y(p.value)}`).join(" ");
    const xticks = variant === "desktop" ? desktopTicks(x) : mobileTicks();
    const segs = phaseSegments(x, g.padL, plotRight);

    // Keep each owner + score together, away from neighboring labels and
    // the week axis. Sorting preserves vertical order; connectors keep the
    // true endpoint visible even when its label needs to move.
    const endLabels = tSeries.flatMap((s, si) => s.pts.length ? [{
      s, si, cy: y(finalValue(s.pts)), labelY: y(finalValue(s.pts)),
    }] : []).sort((a, b) => a.cy - b.cy);
    endLabels.forEach((label, i) => {
      label.labelY = Math.max(label.cy, i ? endLabels[i - 1].labelY + labelGap : g.padT + 12);
    });
    for (let i = endLabels.length - 1; i >= 0; i--) {
      endLabels[i].labelY = Math.min(endLabels[i].labelY,
        i === endLabels.length - 1 ? baselineY - 12 : endLabels[i + 1].labelY - labelGap);
    }

    return (
      <svg viewBox={`0 0 ${g.w} ${H}`} width="100%" role="img"
           aria-label={`Cumulative ${METRIC_LABEL[metric]} points by NFL week`}>
        {measures.map((v, i) => (
          <g key={v}>
            <line x1={g.padL} y1={y(v)} x2={plotRight} y2={y(v)}
                  stroke={i === measures.length - 1 ? "var(--ink)" : "var(--rule)"} strokeWidth="1" />
            <text x={g.padL - 8} y={y(v) + 4} textAnchor="end" fill="var(--dim)"
                  fontFamily={MONO} fontSize="10">{v.toLocaleString(undefined, { maximumFractionDigits: tickDigits })}</text>
          </g>
        ))}

        {hasData ? (
          <>
            {boundaries.map((i) => (
              <g key={i}>
                <line x1={x(i)} y1={g.padT} x2={x(i)} y2={baselineY} stroke="var(--ink)" strokeWidth="1" opacity="0.35" />
                {variant === "desktop" && (
                  <text x={x(i) + 5} y={g.padT + 9} fill="var(--dim)" fontFamily={MONO} fontSize="8" letterSpacing="1.2">
                    {tAxis[i][0]} SEASON
                  </text>
                )}
              </g>
            ))}

            {xticks.map((c, k) => {
              const i = c.i;
              const isTrade = c.kind === "trade";
              const anchor = isTrade ? "start" : c.kind === "end" ? "end" : "middle";
              const showYear = k === 0 || tAxis[i][0] !== tAxis[xticks[k - 1].i][0];
              const label = variant === "mobile"
                ? (isTrade ? "TRADE" : `Wk ${tAxis[i][1]}`)
                : isTrade
                  ? `TRADE · ${tAxis[i][0]} WK ${tAxis[i][1]}`
                  : `${showYear ? `${tAxis[i][0]} ` : ""}WK ${tAxis[i][1]}`;
              return (
                <g key={i}>
                  <line x1={x(i)} y1={baselineY} x2={x(i)} y2={baselineY + 4} stroke="var(--ink)" strokeWidth="1" />
                  <text x={x(i)} y={baselineY + 14} textAnchor={anchor} fill="var(--dim)"
                        fontFamily={MONO} fontSize="9" letterSpacing="0.5">{label}</text>
                </g>
              );
            })}

            {/* SERIES CARRY IDENTITY, ported from Agate 2026-08-16.
                Every line used to be `--ink`, told apart by stroke weight alone
                — 2.5px solid for the winner, 1.25px dashed for everyone else.
                That was Agate's law ("no hue anywhere"), which existed because
                a coloured pixel there could only ever mean a signed figure.
                Furniture ships `--id-N-line` precisely so a chart series can
                carry identity, and a 1.25px dash is the least legible thing on
                the page for anyone who cannot resolve it.

                The STROKE RAMP, not the fill ramp: as 1-3px lines on white only
                two of the six `--id-1..6` fills clear the 3:1 WCAG 1.4.11 asks
                of a graphical object, so a plot's winning series was once its
                faintest line. The drift guard enforces this.

                Weight still carries emphasis — the winner stays 2.5px — but it
                is no longer the ONLY signal, and the dash is gone. */}
            {tSeries.map((s, si) => {
              const solid = s.key === winnerKey;
              return s.pts.length > 1 && (
                <polyline key={s.key} points={path(s.pts)} fill="none"
                          stroke={seriesStroke(si)}
                          strokeWidth={solid ? 2.5 : 1.75}
                          strokeLinejoin="round" strokeLinecap="round" />
              );
            })}

            {/* departure markers: hollow ink square + mono label with a
                ground-colored paint-order halo so the other side's line
                passes behind the text instead of through it. */}
            {tSeries.map((s) =>
              (s.departures ?? []).map((d, di) => {
                const i = tAxis.findIndex(([as, aw]) => as === d.season && aw === d.week);
                if (i < 0 || !s.pts[i]) return null;
                const cx = x(i), cy = y(s.pts[i].value);
                const above = cy - 18 > g.padT;
                const ly = above ? cy - 10 : cy + 18;
                const lx = Math.min(Math.max(cx + 8, g.padL + 4), plotRight - 4);
                const label = variant === "desktop" ? `${d.label} ${d.kind}`.toUpperCase() : d.kind.toUpperCase();
                return (
                  <g key={`${s.key}-dep-${di}`}>
                    <rect x={cx - 4} y={cy - 4} width={8} height={8} fill="var(--bg)" stroke="var(--ink)" strokeWidth="1.5" />
                    <text x={lx} y={ly} textAnchor="start" fill="var(--dim)" fontFamily={MONO}
                          fontSize={variant === "desktop" ? 8.5 : 8} letterSpacing="0.6"
                          style={{ paintOrder: "stroke", stroke: "var(--bg)", strokeWidth: 3, strokeLinejoin: "round" }}>
                      {label}
                    </text>
                  </g>
                );
              }),
            )}

            {/* end-of-line labels — the plot's own right gutter. Mobile has
                none; its labels stack above the plot instead (see JSX below). */}
            {variant === "desktop" && endLabels.map(({ s, si, cy, labelY }) => {
              const solid = s.key === winnerKey;
              const stubX2 = plotRight + 10;
              return (
                <g key={`${s.key}-end`}>
                  <path d={`M ${plotRight} ${cy} L ${plotRight + 4} ${cy} L ${stubX2} ${labelY}`}
                        fill="none" stroke={seriesStroke(si)} strokeWidth={solid ? 2.5 : 1.75} />
                  <text x={stubX2 + 6} y={labelY - 2} fill="var(--ink)" fontFamily={DISPLAY} fontSize="13"
                        fontWeight="700" letterSpacing="-0.02em">{s.label}</text>
                  <text x={stubX2 + 6} y={labelY + 11} fill="var(--dim)" fontFamily={MONO} fontSize="10">
                    {fmtFigure(s.pts[s.pts.length - 1].value)}
                  </text>
                </g>
              );
            })}
          </>
        ) : (
          <text x={(g.padL + plotRight) / 2} y={g.padT + plotH / 2} textAnchor="middle" fill="var(--dim)"
                fontFamily={MONO} fontSize="12" letterSpacing="0.5">
            NO {METRIC_LABEL[metric].toUpperCase()} POINTS
          </text>
        )}

        {/* phase rail — replaces the old amber playoff band and per-side
            injury tints: one 26px-pitch rule under the axis, solid ink for
            postseason weeks, empty for regular. */}
        <text x={g.padL - 8} y={railY + 11.5} textAnchor="end" fill="var(--dim)" fontFamily={MONO}
              fontSize="8" letterSpacing="1.2">PHASE</text>
        {hasData && segs.map((seg, i) => (
          <g key={i}>
            <rect x={seg.x0} y={railY} width={Math.max(seg.x1 - seg.x0, 0)} height={railH}
                  fill={seg.post ? "var(--ink)" : "none"} />
            {i > 0 && <line x1={seg.x0} y1={railY} x2={seg.x0} y2={railY + railH} stroke="var(--ink)" strokeWidth="1" />}
            <text x={(seg.x0 + seg.x1) / 2} y={railY + 11.5} textAnchor="middle"
                  fill={seg.post ? "var(--bg)" : "var(--dim)"} fontFamily={MONO} fontSize="8" letterSpacing="1.2">
              {seg.post ? (variant === "desktop" ? "PLAYOFFS" : "PO") : "REGULAR"}
            </text>
          </g>
        ))}
      </svg>
    );
  }

  return (
    <div>
      {/* A metric switch IS a SegmentControl — `.design` lists "metric
          switches" among its own use cases, so this stops being a bespoke run.
          It also stops scrolling: the run wraps, which is why the
          `overflow-x-auto` exception this block used to hold is gone.

          THE "METRIC" KICKER IS GONE. It was a whisper label pinned left of a
          50px control, and between them they owned a row. The options name
          themselves — a run reading "Total Started Reg Playoff Toilet" has
          never needed the word "Metric" in front of it to be understood, and
          the label was costing more than it explained. `aria-label` still
          carries the name for anyone not reading the pixels. */}
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        {leading}
        {leading ? <div className="h-4 w-px shrink-0 bg-rule" aria-hidden="true" /> : null}
        <SegmentControl<ProductionMetric>
          aria-label="Switch the production metric"
          options={METRICS.map((m) => ({ key: m, label: METRIC_LABEL[m] }))}
          value={metric}
          onChange={setMetric}
        />
      </div>

      {/* Mobile end labels, stacked above the plot (no right gutter at
          390px): a stroke-weight swatch naming which line is which, still no
          key to decode. */}
      {hasData && (
        <div className="min-[701px]:hidden flex flex-col gap-1 mb-2">
          {tSeries.map((s, i) => {
            const solid = s.key === winnerKey;
            const val = s.pts.length ? s.pts[s.pts.length - 1].value : 0;
            return (
              <div key={s.key} className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="inline-block w-4"
                  style={solid
                    ? { height: 2.5, background: seriesStroke(i) }
                    : { height: 1.75, background: seriesStroke(i) }}
                />
                <span className="font-display text-prose font-bold text-ink" style={{ letterSpacing: "-0.02em" }}>
                  {s.label}
                </span>
                <span className="font-mono text-figure text-dim">{fmtFigure(val)}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="hidden min-[701px]:block" data-variant="desktop">{renderPlot("desktop")}</div>
      <div className="min-[701px]:hidden" data-variant="mobile">{renderPlot("mobile")}</div>
    </div>
  );
}
