import type { CSSProperties } from "react";

/**
 * A franchise's competitive window as a position on an ordered five-step ladder.
 *
 */
export interface WindowCellProps {
  /** One of WINDOW_STAGES. An unknown value renders the ladder with nothing active. */
  stage: string;
  style?: CSSProperties;
}

export declare const WINDOW_STAGES: string[];
export declare function WindowCell(props: WindowCellProps): JSX.Element;
