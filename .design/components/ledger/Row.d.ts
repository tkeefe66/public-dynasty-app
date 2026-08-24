import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

/** One rule in a ledger. The first child of a Panel is usually the head. */
export interface RowProps {
  children?: ReactNode;
  /** grid-template-columns, e.g. "minmax(0,1fr) 96px 96px". Must match the head row exactly. */
  cols: string;
  /** total must name what it totals AND equal the rows above it. */
  variant?: "head" | "body" | "total" | "mine";
  /** Renders an <a>. Never nest a button inside a row that is already a link. */
  href?: string;
  onClick?: MouseEventHandler;
  style?: CSSProperties;
}

export declare function Row(props: RowProps): JSX.Element;
