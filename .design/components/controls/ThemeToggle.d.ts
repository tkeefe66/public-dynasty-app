import type { CSSProperties } from "react";

/** Light / Dark. Sets data-theme on <html> at the call site. */
export interface ThemeToggleProps {
  value?: "light" | "dark";
  onChange?: (value: "light" | "dark") => void;
  style?: CSSProperties;
}

export declare function ThemeToggle(props: ThemeToggleProps): JSX.Element;
