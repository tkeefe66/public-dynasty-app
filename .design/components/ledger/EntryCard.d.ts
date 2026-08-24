import type { CSSProperties, ReactNode } from "react";

/**
 * One ledger entry as a card — the narrow-width form of a Row.
 *
 */
export interface EntryCardProps {
  children?: ReactNode;
  /** mine draws a 2px stamp ring; total adds the ink top rule. */
  variant?: "body" | "mine" | "total";
  href?: string;
  style?: CSSProperties;
}

export interface CardListProps { children?: ReactNode; style?: CSSProperties }
export interface MetaLineProps { children?: ReactNode; style?: CSSProperties }
export interface MetaProps {
  /** Mono, dim. Never tinted. */
  label?: string;
  children?: ReactNode;
  /** Tints the VALUE only. Omit for a neutral figure. */
  tone?: "pos" | "neg";
  style?: CSSProperties;
}

export declare function EntryCard(props: EntryCardProps): JSX.Element;
export declare function CardList(props: CardListProps): JSX.Element;
export declare function MetaLine(props: MetaLineProps): JSX.Element;
export declare function Meta(props: MetaProps): JSX.Element;
