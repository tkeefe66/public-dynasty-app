import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

/**
 * The action control. Primary is a stamp fill; ghost is an outline.
 *
 */
export interface ButtonProps {
  children?: ReactNode;
  /** primary = stamp fill. Only ONE primary per view. */
  variant?: "primary" | "ghost";
  /** A Mark name, before the label. */
  icon?: string;
  /** A Mark name, after the label — use for "out to a bigger view". */
  iconAfter?: string;
  disabled?: boolean;
  /** Renders an <a>. A navigation button is a link. */
  href?: string;
  onClick?: MouseEventHandler;
  style?: CSSProperties;
}

export declare function Button(props: ButtonProps): JSX.Element;
