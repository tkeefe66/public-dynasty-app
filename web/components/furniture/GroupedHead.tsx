import type { ReactNode } from "react";
import { Row } from "./Row";
import { mergeClasses } from "./merge";

/**
 * One cap in the naming tier. An ungrouped run of columns takes a capless
 * group (`{ span: 3 }`) rather than being left out — omit `label`, never the
 * group itself, or the arithmetic below stops holding.
 */
export interface HeadGroup {
  /** How many tracks this cap covers. All spans must sum to the track count. */
  span: number;
  /**
   * Omit for an ungrouped run, and omit on any `span: 1` — a cap over one
   * column names what that column already names, 24px higher.
   *
   * A cap must factor out a shared word or a real structural family, and must
   * be **re-checked whenever its columns change**. This is not hypothetical:
   * a "Points" cap here outlived the column trim that removed the three
   * columns making the word shared, leaving it over Total/Start %/GS where
   * only one of the three is a points figure. It is "Production" now.
   */
  label?: string;
}

interface GroupedHeadProps {
  /** One child per column, exactly as `Row variant="head"` takes them. */
  children?: ReactNode;
  /** grid-template-columns. Still repeated **verbatim** on every body row. */
  cols: string;
  /** Left to right, spans summing to the track count. */
  groups: HeadGroup[];
  className?: string;
}

/**
 * Count the tracks a `grid-template-columns` string declares. Parenthesised
 * functions are blanked first, so a `minmax(0, 1fr)` written with a space
 * inside counts as the one track it is rather than two.
 */
function trackCount(cols: string): number {
  let depth = 0;
  let flattened = "";
  for (const ch of cols) {
    if (ch === "(") depth += 1;
    else if (ch === ")") depth -= 1;
    else if (depth === 0) flattened += ch;
    // characters inside parens are dropped entirely
  }
  return flattened.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * A two-tier ledger head — spanning caps over a normal `Row variant="head"`.
 * Mirrors `.design/components/ledger/GroupedHead.jsx`; read its `.prompt.md`
 * for the rules. Eight or more columns only.
 *
 * The 44px label tier is not negotiable: that is a `SortButton`'s tap target,
 * and it is the whole reason this is a separate shape rather than a `Row`
 * variant — `cols` repeated verbatim cannot express a cap that spans tracks.
 *
 * Two ADDITIONS to the `.design/` original, which is style-only the way every
 * primitive in that package is (roles reach `Row` through `...rest`, so none
 * of them carry ARIA of their own):
 *
 * 1. **The ARIA.** Consumers render this inside `role="table"`, so the naming
 *    tier is a real `role="row"` of `role="columnheader"` cells carrying
 *    `aria-colspan` — the accessible form of exactly what the caps draw. A
 *    capless group still emits its (empty) spanning cell, which is why the
 *    visual rule and the ARIA arithmetic are the same rule. The wrapper is a
 *    `rowgroup`: two header rows under one `table` is what a `<thead>` is, and
 *    without it the rows lose their direct parentage. `aria-hidden` would have
 *    been the easy call and is wrong — a cap is not decoration, it carries the
 *    shared word that makes "Total" mean "Total Points".
 * 2. **The dev-mode span check.** A short span sum is not a taste question: it
 *    slides every later cap one column left, which reads as a styling bug, and
 *    the drift guard cannot see arithmetic.
 */
export function GroupedHead({
  children,
  cols,
  groups,
  className = "",
}: GroupedHeadProps) {
  if (process.env.NODE_ENV !== "production") {
    const declared = groups.reduce((n, g) => n + g.span, 0);
    const tracks = trackCount(cols);
    if (declared !== tracks) {
      console.warn(
        `[GroupedHead] spans sum to ${declared} but cols declares ${tracks} ` +
          `tracks. Every column belongs to exactly one group — add a capless ` +
          `{ span: n } for any ungrouped run.`,
      );
    }
  }

  return (
    <div
      role="rowgroup"
      className={mergeClasses("bg-surface-sunk pt-1.5", className)}
    >
      <div
        role="row"
        className="grid items-end gap-2.5 px-3.5 h-[18px] font-mono text-label font-medium uppercase tracking-[0.16em] text-dim"
        style={{ gridTemplateColumns: cols }}
      >
        {groups.map((g, i) => (
          <div
            key={i}
            role="columnheader"
            aria-colspan={g.span}
            /* The rule spans the group's tracks and their internal gaps but
             * stops at the group boundary — the 10px break between caps is
             * what reads as the division. */
            className={`pb-[3px] truncate ${g.label ? "border-b border-rule-strong" : ""}`}
            style={{ gridColumn: `span ${g.span}` }}
          >
            {g.label || ""}
          </div>
        ))}
      </div>
      <Row role="row" variant="head" cols={cols}>
        {children}
      </Row>
    </div>
  );
}
