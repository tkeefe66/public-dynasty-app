import type { CSSProperties } from "react";

/** A franchise identity mark — its colour and initial. */
export interface AvatarProps {
  name?: string;
  /** An --id-* token. Identity only; never a data value. */
  color?: string;
  size?: number;
  style?: CSSProperties;
}

export declare function Avatar(props: AvatarProps): JSX.Element;
