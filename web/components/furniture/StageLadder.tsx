import { WINDOW_STAGES } from "@/lib/window";

/* ---------------------------------------------------------------------------
 * Ported from `.design/components/data/WindowCell.jsx`. WINDOW_STAGES is an
 * ORDERED five-step sequence, low to high — not four quadrants. That file
 * records a scatter plot being tried and abandoned, because it made an ordered
 * position look like a coordinate.
 *
 * Shape is the SegmentControl's: a sunk `--surface-sunk` track, pill radius,
 * and the active rung filled with `--stamp` and reversed out in `--stamp-ink`.
 * Stamp is a ground you reverse type out of, and "the stage you are on" is one
 * of its five sanctioned slots (an active segment).
 * ------------------------------------------------------------------------ */

export function StageLadder({ stage }: { stage?: string | null }) {
  return (
    <ul
      className="flex gap-0.5 rounded-pill bg-surface-sunk p-1"
      aria-label="Competitive window"
    >
      {WINDOW_STAGES.map((s) => {
        const on = s === stage;
        return (
          <li
            key={s}
            data-on={on ? "true" : "false"}
            aria-current={on ? "true" : undefined}
            className={`flex min-h-[30px] flex-1 items-center justify-center whitespace-nowrap rounded-pill px-2 font-mono text-label uppercase tracking-[0.06em] ${
              on ? "bg-stamp font-bold text-stamp-ink" : "text-dim"
            }`}
          >
            {s}
          </li>
        );
      })}
    </ul>
  );
}
