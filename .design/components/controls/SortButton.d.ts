import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

/**
 * A sortable column header.
 *
 * `aria-sort` belongs on the WRAPPING `columnheader` cell, never on this
 * button — it is invalid on `role="button"` and the platform drops it. See
 * the `.jsx` note; a real ledger shipped announcing no sort state because it
 * lived here.
 */
export interface SortButtonProps {
  children?: ReactNode;
  /** none | ascending | descending — drives the mark, and whether it is shown
   *  at all: the mark is invisible until the column is active, or hovered, or
   *  focused. Its box is reserved at every state so nothing shifts. */
  sort?: "none" | "ascending" | "descending";
  onClick?: MouseEventHandler;
  /** right for a figure column, so the label hugs its numbers. */
  align?: "left" | "right";
  /** Column name for this button's own accessible name ("Sort by Total,
   *  currently descending"). Falls back to `children` when that is a plain
   *  string. Without it a control reading "#" announces as "#". */
  label?: string;
  style?: CSSProperties;
}

export declare function SortButton(props: SortButtonProps): JSX.Element;
