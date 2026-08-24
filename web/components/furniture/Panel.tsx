import type { ComponentPropsWithoutRef, ReactNode } from "react";

/**
 * A ledger: solid ground, one radius, one elevation.
 *
 * This replaces Agate's `Ruled`, and the replacement is not cosmetic. Under
 * Agate the ground was a `repeating-linear-gradient` and the stripes WERE the
 * row dividers, so no row carried a border. A Panel is solid, so **every row
 * draws its own `--rule` hairline** — see `Row`. Getting this backwards is the
 * single most commonly missed line in the system.
 *
 * `overflow-hidden` is load-bearing: without it the first and last rows' square
 * corners paint over the panel's 16px radius.
 */
export function Panel({
  className = "",
  children,
  ...rest
}: ComponentPropsWithoutRef<"div"> & { children?: ReactNode }) {
  return (
    <div
      className={`overflow-hidden rounded-panel border border-rule-strong bg-surface shadow-panel ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}
