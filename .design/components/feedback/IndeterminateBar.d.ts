import type { CSSProperties } from "react";

/** The system's one loading indicator. One per view. */
export interface IndeterminateBarProps {
  /** Mono label above the track: what is loading. */
  label?: string;
  style?: CSSProperties;
}

export declare function IndeterminateBar(props: IndeterminateBarProps): JSX.Element;
