import type { CSSProperties } from "react";

/**
 * A magnitude bar in a sunk track. Signed bars grow from a centre line.
 *
 */
export interface BarProps {
  value: number;
  /** The scale ceiling. Every bar in one group must share it. */
  max?: number;
  /** Draws a centre line and colours by sign, using the --*-bar pair. */
  signed?: boolean;
  height?: number;
  style?: CSSProperties;
}

export declare function Bar(props: BarProps): JSX.Element;
