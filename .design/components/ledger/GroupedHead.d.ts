import type { CSSProperties, ReactNode } from "react";

/** One cap in the naming tier. A capless group is how an ungrouped run of
 *  columns keeps the arithmetic honest — omit `label`, never the group. */
export interface HeadGroup {
  /** How many tracks this cap covers. All spans must sum to the track count. */
  span: number;
  /** Omit for an ungrouped run, and omit on any `span: 1` — a cap over one
   *  column names what that column already names, 24px higher. A cap must
   *  factor out a shared word or a real structural family, and must be
   *  re-checked whenever its columns change: a trim can quietly remove the
   *  columns that made the word shared. */
  label?: string;
}

/** A two-tier ledger head. Eight or more columns only: below that a single
 *  `Row variant="head"` is not crowded and the extra 24px buys nothing. */
export interface GroupedHeadProps {
  /** One child per column, exactly as `Row variant="head"` takes them. */
  children?: ReactNode;
  /** grid-template-columns. Still repeated VERBATIM on every body row. */
  cols: string;
  /** Left to right, spans summing to the track count. */
  groups: HeadGroup[];
  style?: CSSProperties;
}

export declare function GroupedHead(props: GroupedHeadProps): JSX.Element;
