"use client";

import { Children, type ReactNode } from "react";
import { Panel } from "../furniture/Panel";

/* ---------------------------------------------------------------------------
 * Furniture — franchise-page shared vocabulary. Ported off Agate.
 *
 * `Card`/`CardHead` are re-exported as the Furniture `Section`/`SectionTitle`
 * under their old names, so every existing call site on this page is unchanged
 * while the heading underneath becomes Bricolage mixed case. A section is still
 * a heading over a hairline: the panel belongs to the LEDGER inside a section,
 * not to the section wrapper, or you get a box inside a box.
 *
 * `StatStrip` is the one with a real behaviour change. Under Agate it had to
 * hand-split its cells into pairs and render two whole variants, because
 * `.ruled > *` clamped every direct child to one 26px rule and a two-line strip
 * clipped. A `Row` sets `min-height`, not `height`, so the strip can simply
 * change its column count at the breakpoint — one render, no clipping, and the
 * cell order can no longer disagree between the two variants.
 * ------------------------------------------------------------------------ */

export { Section as Card, SectionTitle as CardHead } from "../furniture/Section";

/** One labelled cell: whisper label + figure. The value never truncates
 *  (flex-none, nowrap); the label degrades with an ellipsis instead — the label
 *  is recoverable from context, a clipped figure is not. `sub` renders as a
 *  trailing dim caption on the same line rather than a second rule. */
export function Stat({
  label, value, tone, sub,
}: { label: string; value: ReactNode; tone?: string; sub?: ReactNode }) {
  return (
    <div className="flex min-w-0 items-baseline gap-1.5">
      <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-label uppercase tracking-[0.11em] text-dim">
        {label}
      </span>
      <span className={`flex-none whitespace-nowrap font-mono text-figure font-semibold tabular text-ink ${tone ?? ""}`}>
        {value}
      </span>
      {sub != null && (
        <span className="flex-none whitespace-nowrap font-mono text-label text-dim">{sub}</span>
      )}
    </div>
  );
}

/** A row of `Stat` cells — the rings-strip pattern, reused wherever a tab needs
 *  a quick labelled-figure strip.
 *
 *  Four cells cannot hold a letterspaced label and its figure at 390px, so the
 *  strip drops to two columns there and wraps onto as many rows as it needs.
 *  That is a grid property now rather than two hand-maintained renders. */
export function StatStrip({ children }: { children: ReactNode }) {
  const items = Children.toArray(children);
  return (
    <Panel>
      {/* Not a `Row`: a Row is one ledger entry with a column contract, and
          this strip wraps onto however many lines it needs. Borrowing Row here
          would claim a row semantics the content does not have. */}
      <div className="grid grid-cols-2 gap-x-5 gap-y-2.5 px-3.5 py-3 min-[701px]:grid-cols-4">
        {items}
      </div>
    </Panel>
  );
}
