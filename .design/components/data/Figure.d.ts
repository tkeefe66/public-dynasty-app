import type { CSSProperties } from "react";

/**
 * Every number in the app. Mono, tabular; signed values coloured.
 *
 */
export interface FigureProps {
  value: number | string | null | undefined;
  /** Renders the sign always, and colours --pos/--neg. Only for a margin or a delta. */
  signed?: boolean;
  dp?: number;
  /** Any CSS length. Above ~13px use pos-strong/neg-strong instead of signed. */
  size?: string;
  align?: "left" | "right" | "center";
  /** Force --dim — a value that exists but does not carry weight. */
  dim?: boolean;
  /** A unit that whispers: "pg", "pts". Rendered in --dim. */
  suffix?: string;
  style?: CSSProperties;
}

export declare function Figure(props: FigureProps): JSX.Element;
