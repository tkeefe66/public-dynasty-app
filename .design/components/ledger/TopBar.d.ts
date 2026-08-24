import type { CSSProperties, ReactNode } from "react";

/**
 * The product's one chrome strip: wordmark, league, nav, and a right group.
 *
 */
export interface TopBarNavItem {
  label: string;
  href?: string;
  /** A Mark name. */
  icon?: string;
  on?: boolean;
}

export interface TopBarProps {
  wordmark?: string;
  /** The current league. Holds identity on screens with no masthead. */
  league?: string;
  items?: TopBarNavItem[];
  /** ThemeToggle, a week note, an account link. */
  right?: ReactNode;
  style?: CSSProperties;
}

export declare function TopBar(props: TopBarProps): JSX.Element;
