import type { CSSProperties, InputHTMLAttributes } from "react";

/** A text input with an optional mono label and hint. */
export interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Mono uppercase, above the input. Also generates the id/for pairing. */
  label?: string;
  /** One line under the input — what a valid value looks like. */
  hint?: string;
  style?: CSSProperties;
}

export declare function Field(props: FieldProps): JSX.Element;
