import type { CSSProperties } from "react";

/**
 * The system's only single-select switch. An underline run — the active option
 * in full ink with a 2px stamp underline, no well and no pill. ~24px of ink
 * over a 44px tap target.
 *
 */
export interface SegmentControlProps {
  /** Strings, or {value,label} when the label differs from the value. */
  options: Array<string | { value: string; label: string }>;
  value: string;
  onChange?: (value: string) => void;
  /** aria-label for the group. Required for a screen reader to announce it. */
  label?: string;
  style?: CSSProperties;
}

export declare function SegmentControl(props: SegmentControlProps): JSX.Element;
