import type { CSSProperties } from "react";

/**
 * A franchise grade letter, on the A-F tone ramp.
 *
 */
export interface GradeLetterProps {
  /** "A" | "A-" | "B+" … The first character picks the tone. */
  grade: string;
  /** Px. 78 in a franchise hero, 44 in a list, 15 inline. */
  size?: number;
  style?: CSSProperties;
}

export declare function GradeLetter(props: GradeLetterProps): JSX.Element;
