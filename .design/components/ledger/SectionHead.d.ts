import type { CSSProperties, ReactNode } from "react";

/** A section heading, optionally collapsible. Mixed case, never uppercase. */
export interface SectionHeadProps {
  title: string;
  /** A mono count or scope on the right: "12 franchises", "All-time". */
  aside?: ReactNode;
  collapsible?: boolean;
  open?: boolean;
  onToggle?: () => void;
  style?: CSSProperties;
}

export declare function SectionHead(props: SectionHeadProps): JSX.Element;
