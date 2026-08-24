import type { CSSProperties, ReactNode } from "react";

/**
 * A ledger container: solid ground, one radius, one elevation.
 *
 */
export interface PanelProps {
  /** Row elements. The first should usually be variant="head". */
  children?: ReactNode;
  style?: CSSProperties;
}

export declare function Panel(props: PanelProps): JSX.Element;
