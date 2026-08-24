import React from "react";
import { Mark } from "./Mark.jsx";

/**
 * A sortable column header. The 44px target lives on the BUTTON, not the row,
 * so a header stays operable at any density.
 *
 * `aria-sort` is NOT here, and must not come back. It is valid only on
 * `columnheader`/`rowheader`/`gridcell`, so on `role="button"` the platform
 * drops it: a real ledger built from this component shipped announcing no
 * sort state at all, and its tests read the attribute off the button too, so
 * they stayed green through the whole defect. The WRAPPING header cell owns
 * it. What this button owns is its own accessible name — give it an
 * aria-label like "Sort by Total, currently descending", or a control whose
 * visible text is "#" announces as "#".
 *
 * Inherits font, letterSpacing and textTransform from the header row so a
 * sortable column is typographically identical to a fixed one — a column that
 * looks different because it happens to be sortable is a bug.
 *
 * THE INACTIVE MARK IS INVISIBLE, revealed on hover or keyboard focus. It was
 * drawn at 0.3 on every column, which on a ten-column ledger is ten arrows of
 * which nine say nothing. Measured on a real board, that plus each column's
 * definition trigger put 33px of chrome into tracks cut for plain text and
 * re-jumbled a header a naming tier had just been added to un-jumble.
 *
 * It is OPACITY, never display/width — the mark's box is always reserved, or
 * the label jumps sideways by 12px on hover and the calm you bought is gone.
 * Hiding the mark buys quiet, not room: a track must still fit label + mark +
 * trigger.
 *
 * :hover/:focus-visible cannot be expressed in the inline styles this package
 * uses, so the reveal is the one part a consumer implements itself (the app
 * mirror does it with a group-hover utility). Everything else — the reserved
 * box, the active state, the direction the mark reads — is here.
 *
 * ACCEPTED GAP: a touch device wide enough for the desktop table gets neither
 * :hover nor :focus-visible, so a sortable header shows no affordance until it
 * is tapped. Documented rather than solved — an always-visible mark is what
 * this change removed.
 */
export function SortButton({ children, sort = "none", onClick, align = "left", label, style }) {
  const active = sort !== "none";
  const name = label ?? (typeof children === "string" ? children : undefined);
  return (
    <button
      type="button"
      aria-label={name ? `Sort by ${name}${active ? `, currently ${sort}` : ""}` : undefined}
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: align === "right" ? "flex-end" : "flex-start",
        width: align === "right" ? "100%" : undefined,
        gap: 5,
        minHeight: 44,
        padding: 0,
        background: "none",
        border: 0,
        font: "inherit",
        letterSpacing: "inherit",
        textTransform: "inherit",
        color: active ? "var(--ink)" : "inherit",
        cursor: "pointer",
        ...style,
      }}
    >
      {children}
      <Mark
        name={sort === "ascending" ? "sort-asc" : "sort-desc"}
        size={12}
        style={{ opacity: active ? 1 : 0, transition: "opacity 120ms" }}
      />
    </button>
  );
}
