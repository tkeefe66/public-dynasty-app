import type { CSSProperties, MouseEventHandler, ReactNode } from "react";

/** "Out to a bigger view". A quiet mono link, never a second button. */
export interface MonoLinkProps {
  children?: ReactNode;
  href?: string;
  onClick?: MouseEventHandler;
  style?: CSSProperties;
}

export declare function MonoLink(props: MonoLinkProps): JSX.Element;
