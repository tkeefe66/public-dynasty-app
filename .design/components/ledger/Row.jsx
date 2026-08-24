import React from "react";

/**
 * One entry in a ledger. `cols` is a grid-template-columns string, repeated
 * verbatim on the head row and every body row — that repetition IS the column
 * contract, and a mismatch between the two is the most common ledger bug.
 *
 *   head  — sunk ground, mono label type, 44px so a SortButton fits
 *   total — sunk ground and a 2px ink top rule. It must NAME what it totals,
 *           and it must equal the rows above it: a headline figure that does
 *           not reconcile with its rows is a lie, and filtering a ledger
 *           without recomputing its total shipped once.
 *   mine  — the signed-in user's entry. Stamp, because "you" is the product
 *           speaking rather than a data value.
 */
export function Row({ children, cols, variant = "body", href, onClick, style }) {
  const head = variant === "head";
  const total = variant === "total";
  const mine = variant === "mine";
  const s = {
    display: "grid",
    gridTemplateColumns: cols,
    alignItems: "center",
    gap: 10,
    padding: "0 14px",
    minHeight: head ? 44 : "var(--rule-pitch)",
    fontFamily: "var(--font-mono)",
    fontSize: head ? "var(--text-label)" : "var(--text-figure)",
    fontVariantNumeric: "tabular-nums",
    color: "var(--dim)",
    letterSpacing: head ? ".12em" : undefined,
    textTransform: head ? "uppercase" : undefined,
    background: head || total ? "var(--surface-sunk)" : mine ? "color-mix(in srgb, var(--stamp) 6%, var(--surface))" : undefined,
    borderTop: total ? "2px solid var(--ink)" : head ? undefined : "1px solid var(--rule)",
    borderBottom: head ? "1px solid var(--rule)" : undefined,
    boxShadow: mine ? "inset 3px 0 0 var(--stamp)" : undefined,
    fontWeight: total ? 500 : undefined,
    textDecoration: "none",
    ...style,
  };
  if (href) return <a href={href} style={s}>{children}</a>;
  return <div onClick={onClick} style={s}>{children}</div>;
}
