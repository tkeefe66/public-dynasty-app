import type { CSSProperties } from "react";
import { FX_ICON_PATHS, type MarkName } from "./fx-icon-paths";

// Re-exported so a call site can import the name union from the component it
// uses, rather than reaching into the path data.
export type { MarkName };

interface MarkProps {
  name: MarkName;
  /** Pixel size of the square viewBox. Defaults to 12 (control size). */
  size?: number;
  /** Stroke weight. Defaults to 1.6 — the one weight this set draws at. */
  strokeWidth?: number;
  className?: string;
  style?: CSSProperties;
}

/**
 * One of the nineteen marks, stroked — the Furniture replacement for
 * `web/components/agate/Icon.tsx` (the cut set). Named `Mark` rather than
 * `Icon` because both sets ship from this codebase; a call site that wants
 * Furniture wants this one.
 *
 * `stroke` is `currentColor` and there is no fill, so a mark reads on paper,
 * on slate, and reversed out of a stamp fill with no variants. Never hard-code
 * a colour on a mark and never give it `--pos`/`--neg` — those belong to
 * figures; near data a mark stays `--dim`.
 *
 * Props mirror `agate/Icon.tsx` (`name`, `size`, `className`) exactly, so a
 * call site can swap `Icon` for `Mark` without touching anything but the
 * import — the nineteen names are identical between the two sets.
 *
 * Accessibility matches `agate/Icon.tsx`: a mark is always `aria-hidden`,
 * decorative by default. A control whose ONLY content is a mark (an
 * icon-only button) must put the label on the control itself
 * (`<button aria-label="…">`), not on the mark — this component has no
 * label prop, on purpose, to match the existing pattern every call site
 * already relies on.
 *
 * Usable from server and client components alike — no `"use client"` here.
 */
export function Mark({ name, size = 12, strokeWidth = 1.6, className, style }: MarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
      style={{ display: "block", flex: "0 0 auto", ...style }}
    >
      <path d={FX_ICON_PATHS[name]} />
    </svg>
  );
}

/**
 * Alias for the nineteen-name union. `agate/Icon` exported this as `IconName`
 * and `TopBar.tsx` imports it as a TYPE, so without this the "mechanical import
 * swap" fails to compile at exactly one of nine call sites. Caught by review
 * before the swap ran. Prefer `MarkName` in new code.
 */
export type IconName = MarkName;
