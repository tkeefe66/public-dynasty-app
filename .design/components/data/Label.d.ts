import type { CSSProperties, ReactNode } from "react";

/** A mono uppercase label at the 8.5px type floor. */
export interface LabelProps {
  children?: ReactNode;
  /** stamp marks the signed-in user ("You"); ink lifts a value out of dim. */
  tone?: "dim" | "ink" | "stamp";
  size?: string;
  style?: CSSProperties;
}

export interface KickerProps { children?: ReactNode; style?: CSSProperties }

export declare function Label(props: LabelProps): JSX.Element;
export declare function Kicker(props: KickerProps): JSX.Element;
