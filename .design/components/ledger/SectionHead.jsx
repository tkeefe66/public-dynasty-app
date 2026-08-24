import React from "react";
import { Mark } from "../controls/Mark.jsx";

/**
 * A section heading. Mixed case at 800 — Agate set these in Archivo 900
 * uppercase, and that shout is a large part of what read as dated.
 *
 * Collapsible heads keep a 44px target and carry role/aria-expanded
 * (SectionCollapse.tsx). Two things that have gone wrong here: a collapse must
 * hide EVERY body that belongs to the section (a Furniture ledger has two, the
 * rows and the cards), and it should default OPEN on a phone, where there is
 * no hover to preview what is inside and the whole page is one scroll.
 */
export function SectionHead({ title, aside, collapsible = false, open = true, onToggle, style }) {
  const base = {
    display: "flex",
    alignItems: collapsible ? "center" : "baseline",
    justifyContent: "space-between",
    gap: 12,
    margin: "26px 0 10px",
    minHeight: collapsible ? 44 : undefined,
    cursor: collapsible ? "pointer" : undefined,
    userSelect: collapsible ? "none" : undefined,
    ...style,
  };
  const inner = (
    <>
      <span style={{ display: "flex", alignItems: "center", minWidth: 0 }}>
        {collapsible ? (
          <span style={{ display: "inline-flex", color: "var(--dim)", marginRight: 7 }}>
            <Mark name={open ? "open" : "closed"} size={12} />
          </span>
        ) : null}
        <h2 style={{ margin: 0, fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "var(--text-section)", letterSpacing: "-.026em" }}>
          {title}
        </h2>
      </span>
      {aside ? (
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-label)", letterSpacing: ".14em", textTransform: "uppercase", color: "var(--dim)", whiteSpace: "nowrap" }}>
          {aside}
        </span>
      ) : null}
    </>
  );
  if (!collapsible) return <div style={base}>{inner}</div>;
  return (
    <div role="button" tabIndex={0} aria-expanded={open} onClick={onToggle} style={base}>
      {inner}
    </div>
  );
}
