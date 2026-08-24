import type { CSSProperties, ReactNode } from "react";

/**
 * A trade ruling: the verdict first, the detail underneath.
 *
 */
export interface RulingStampProps {
  /** The kicker: "Ruling", "Trade of the week". */
  verdict?: string;
  /** Who won. The headline. */
  winner: string;
  /** One sentence of why, with the margin in it. */
  detail?: ReactNode;
  /** A closing classification: "Lopsided", "Fair", "Too early to call". */
  tag?: string;
  style?: CSSProperties;
}

export declare function RulingStamp(props: RulingStampProps): JSX.Element;
