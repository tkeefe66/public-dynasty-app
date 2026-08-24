import type { CSSProperties, ReactNode } from "react";

/**
 * The league masthead: a stamp ground with the name reversed out of it.
 *
 */
export interface StampBandProps {
  /** Mono uppercase above the name. */
  kicker?: ReactNode;
  /** The league or franchise name. Two lines maximum, never truncated. */
  title?: string;
  /** A mono facts line: "12 teams · 148 trades graded". */
  meta?: ReactNode;
  children?: ReactNode;
  style?: CSSProperties;
}

export declare function StampBand(props: StampBandProps): JSX.Element;
