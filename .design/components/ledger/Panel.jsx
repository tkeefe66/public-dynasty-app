import React from "react";

/**
 * A ledger. THE ONE RULE THAT MATTERS: a Furniture panel has a SOLID ground,
 * so the stripe that used to divide rows under Agate is gone and `Row` draws
 * its own top rule. A panel with a background and no row rules renders as one
 * undivided block — that failure shipped once.
 *
 * overflow:hidden is what clips the children to the radius. It also means a
 * floating layer (a tooltip) inside a panel must be portalled to <body>.
 */
export function Panel({ children, style }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        borderRadius: "var(--radius)",
        boxShadow: "var(--shadow)",
        overflow: "hidden",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
