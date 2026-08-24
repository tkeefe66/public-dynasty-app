import React from "react";
import { FX_ICON_PATHS } from "./fx-icon-paths.js";

/**
 * One of the nineteen marks, stroked. Named Mark rather than Icon because
 * Agate's Icon is the CUT set and both are exported from this system — a call
 * site that wants Furniture wants this one.
 *
 * stroke is currentColor and there is no fill, so a mark reads on paper, on
 * slate, and reversed out of a stamp fill with no variants.
 */
export function Mark({ name, size = 12, strokeWidth = 1.6, style }) {
  const d = FX_ICON_PATHS[name];
  if (!d) return null;
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
      style={{ display: "block", flex: "0 0 auto", ...style }}
    >
      <path d={d} />
    </svg>
  );
}
