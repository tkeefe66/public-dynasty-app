import type { CSSProperties } from "react";

/**
 * One of the nineteen first-party marks, stroked on a 16px grid.
 *
 */
export interface MarkProps {
  /** One of FX_ICON_NAMES. An unknown name renders nothing. */
  name: string;
  /** Px. 12 in a row or a label, 14-16 in a button. */
  size?: number;
  strokeWidth?: number;
  style?: CSSProperties;
}

export declare function Mark(props: MarkProps): JSX.Element | null;
