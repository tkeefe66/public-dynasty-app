import type { CSSProperties, ReactNode } from "react";

/**
 * The definition behind a label. Positioned against the viewport so a Panel's
 * overflow:hidden cannot clip it.
 *
 */
export interface TooltipProps {
  /** The label being defined. Also builds the aria-label. */
  title?: string;
  /** Plain prose. What this signal is, in a sentence. */
  body?: ReactNode;
  /** Optional mono footer: how it is calculated. */
  formula?: ReactNode;
  /** Custom trigger. Defaults to the info mark. */
  children?: ReactNode;
  style?: CSSProperties;
}

export declare function Tooltip(props: TooltipProps): JSX.Element;
