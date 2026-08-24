import type { CSSProperties, ReactNode } from "react";

/** A franchise or player name. Display face at every density. */
export interface NameProps {
  children?: ReactNode;
  /** row truncates; card wraps and sets one step larger. */
  on?: "row" | "card";
  style?: CSSProperties;
}

export declare function Name(props: NameProps): JSX.Element;
