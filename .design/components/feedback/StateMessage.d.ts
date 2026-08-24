import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

/**
 * Empty, error and not-found states.
 *
 */
export interface StateMessageProps {
  tone?: "empty" | "error" | "done";
  /** What happened, in the product's voice — never "No data available". */
  title: string;
  /** Why, and what it means for this reader. */
  body?: ReactNode;
  /** The one action that resolves it. */
  action?: string;
  onAction?: MouseEventHandler;
  href?: string;
  style?: CSSProperties;
}

export declare function StateMessage(props: StateMessageProps): JSX.Element;
