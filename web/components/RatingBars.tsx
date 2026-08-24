import type { ReactNode } from "react";
import { Row } from "./furniture/Row";

/* ---------------------------------------------------------------------------
 * Agate — Ink Bars (design_handoff_agate/DESIGN.md § "Named rules" — "Ink
 * Bars"; CLAUDE_CODE.md § Commit 6). A contribution bar is ink on a center
 * axis, never colored — "a bar is not a number, so a bar is never colored."
 * Direction and length carry the magnitude; the figure beside it carries the
 * sign in --pos/--neg. Both existing safeguards are kept: the scale is the
 * max over every pillar contribution AND every signal contribution in the
 * group (not the largest signal alone), and the half-track is clamped with
 * Math.min(50, …). Under 700px the bar column is dropped entirely — the
 * `hidden min-[701px]:block` wrapper removes it from grid flow so the
 * 2-column mobile template (label, figure) lays out correctly with no gap
 * where the bar used to sit.
 * ------------------------------------------------------------------------ */

export function fmtPts(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

/** A signed magnitude bar in a SUNK TRACK, diverging from a centre line.
 *
 *  COLOUR IS CORRECT HERE, and it was wrong before. Agate's rule was absolute —
 *  "a bar is not a number, so a bar is never colored" — because in a system
 *  whose only colour was a signed figure, a coloured pixel could mean nothing
 *  else. Furniture replaced `InkBar` with `Bar` precisely to lift that: a
 *  contribution IS a signed value, and `.design/tokens/colors.css` ships a
 *  THIRD pair for it — `--pos-bar` / `--neg-bar`, weight-matched so neither hue
 *  reads as "more" at equal length. They are deliberately NOT `--pos`/`--neg`:
 *  a bar is a large solid area, and the figure pair is tuned for 10-13px type,
 *  where --neg runs hotter and would pull red forward.
 *
 *  The track is `--rule` with a `--rule-strong` centre line, per
 *  `.design/components/data/Bar.jsx`. A negative bar is SOLID and grows
 *  leftward — that file records a hollow outline being tried and abandoned,
 *  because at real magnitudes many bars are 3-8px wide and a ring leaves no
 *  interior at all. */
/** Exported so a ledger with a different column contract (the Outlook tab's
 *  five-column Assets ledger) can draw the SAME bar without inheriting
 *  ContributionRow's three-track grid. The bar is the grammar; the grid is
 *  the sentence. */
export function DivergeBar({ points, scale }: { points: number; scale: number }) {
  const mag = Math.min(50, (Math.abs(points) / scale) * 50);
  const pos = points >= 0;
  return (
    <div className="relative flex h-[26px] items-center" aria-hidden="true">
      <div className="relative h-[5px] w-full rounded-sm bg-rule">
        <span className="absolute -top-px -bottom-px left-1/2 w-px bg-rule-strong" />
        {points !== 0 && (
          <span
            className={`absolute top-0 bottom-0 rounded-sm ${pos ? "bg-pos-bar" : "bg-neg-bar"}`}
            style={pos ? { left: "50%", width: `${mag}%` } : { right: "50%", width: `${mag}%` }}
          />
        )}
      </div>
    </div>
  );
}

export function ContributionRow({
  label, weight, points, scale, signal, tooltip,
}: {
  label: string; weight?: number; points: number; scale: number; signal?: boolean;
  /** Optional info trigger (an `InfoTooltip`) rendered beside the label —
   *  Leaderboard.tsx's per-signal/pillar definitions. */
  tooltip?: ReactNode;
}) {
  const figureTone = points > 0 ? "text-pos-strong" : points < 0 ? "text-neg-strong" : "text-dim";
  return (
    <Row
      className="items-center grid-cols-[minmax(0,1fr)_52px] min-[701px]:grid-cols-[168px_1fr_52px]"
    >
      <span
        className={`flex items-baseline gap-1.5 min-w-0 overflow-hidden ${
          signal
            ? "pl-3.5 font-mono text-figure text-dim"
            : "font-display text-name font-bold tracking-[-0.024em] text-ink"
        }`}
      >
        <span className="truncate">{label}</span>
        {weight != null && <span className="font-mono text-label text-dim shrink-0">{Math.round(weight * 100)}%</span>}
        {tooltip && <span className="shrink-0">{tooltip}</span>}
      </span>
      <div className="hidden min-[701px]:block">
        <DivergeBar points={points} scale={scale} />
      </div>
      <span className={`text-right font-mono text-figure font-semibold tabular whitespace-nowrap ${figureTone}`}>
        {fmtPts(points)}
      </span>
    </Row>
  );
}
