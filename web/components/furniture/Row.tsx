import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { mergeClasses } from "./merge";

// Re-exported so tests/row-merge.test.ts keeps its import path.
export { mergeClasses };

export type RowVariant = "head" | "body" | "total" | "mine";

interface RowProps extends Omit<ComponentPropsWithoutRef<"div">, "style"> {
  /**
   * A `grid-template-columns` string, repeated **verbatim** on the head row and
   * every body row. That repetition IS the column contract, and a mismatch
   * between the two is the most common ledger bug. Omit for a full-width row.
   */
  cols?: string;
  variant?: RowVariant;
  children?: ReactNode;
}

export function Row({
  cols,
  variant = "body",
  className = "",
  children,
  ...rest
}: RowProps) {
  const base =
    "grid items-center gap-2.5 px-3.5 font-mono text-figure tabular text-dim";
  const byVariant: Record<RowVariant, string> = {
    /* GOTCHA: the `uppercase` here does not reach a <button> or <select> inside
     * the row. Tailwind's preflight sets `text-transform: none` on both, so an
     * interactive header — a sort control, a filter — must repeat `uppercase`
     * on itself or it renders in whatever case its label string happens to be.
     * This split the standings header in two before it was spotted. */
    head: "min-h-tap bg-surface-sunk border-b border-rule text-label uppercase tracking-[0.12em]",
    body: "min-h-[var(--rule-pitch)] border-t border-rule",
    total: "min-h-[var(--rule-pitch)] bg-surface-sunk border-t-2 border-ink font-medium text-ink",
    /* The marker is a 3px DRAWN line, not an elevation — so it is a border.
     * This was first written as a zero-blur inset via the elevation utility,
     * and the drift guard rejected it correctly: to any reader or tool that
     * utility is indistinguishable from a second elevation, whatever the blur
     * radius says. The left padding drops by the border's width so the marker
     * does not shift the row's content out of column with its neighbours. */
    mine: "min-h-[var(--rule-pitch)] border-t border-rule border-l-[3px] border-l-stamp bg-stamp-wash pl-[11px]",
  };
  return (
    <div
      className={mergeClasses(`${base} ${byVariant[variant]}`, className)}
      style={cols ? { gridTemplateColumns: cols } : undefined}
      {...rest}
    >
      {children}
    </div>
  );
}
