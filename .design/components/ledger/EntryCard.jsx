import React from "react";

/**
 * ONE ENTRY, AS A CARD — the answer to the mobile split.
 *
 * Under Agate a ledger row was clamped to the rule pitch, so an entry needing
 * two visual lines became two rules, and any divider drawn between children
 * cut a single franchise in half. A card has EDGES, so its boundary IS the
 * entry boundary: no wrapper, no per-rule border logic, no clamp. This is why
 * a phone gets cards rather than narrower rows.
 *
 * Rejected alternatives, on the record: an entry wrapper carrying the border
 * (keeps the clamp and its workarounds) and dropping columns on mobile (loses
 * data — the reason the app's guard bans horizontal scroll is that its tables
 * refuse to).
 */
export function EntryCard({ children, variant = "body", href, style }) {
  const s = {
    display: "grid",
    gap: 10,
    background: "var(--surface)",
    borderRadius: "var(--radius)",
    boxShadow:
      variant === "mine"
        ? "0 0 0 2px var(--stamp), var(--shadow)"
        : "var(--shadow)",
    borderTop: variant === "total" ? "2px solid var(--ink)" : undefined,
    padding: "13px 14px",
    color: "inherit",
    textDecoration: "none",
    ...style,
  };
  if (href) return <a href={href} style={s}>{children}</a>;
  return <div style={s}>{children}</div>;
}

/** The stack. gap, not margins — a deleted card must not leave a hole. */
export function CardList({ children, style }) {
  return <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)", ...style }}>{children}</div>;
}

/**
 * A card's secondary facts. Each item wraps as a WHOLE unit: a broken
 * "2nd · peaking" reads as two facts rather than one.
 */
export function MetaLine({ children, style }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 14px", paddingTop: 9, borderTop: "1px solid var(--rule)", ...style }}>
      {children}
    </div>
  );
}

/** One fact in a MetaLine. `tone` colours the value, never the label. */
export function Meta({ label, children, tone, style }) {
  const color = tone === "pos" ? "var(--pos-strong)" : tone === "neg" ? "var(--neg)" : "var(--ink)";
  return (
    <div style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, fontVariantNumeric: "tabular-nums", color: "var(--dim)", whiteSpace: "nowrap", ...style }}>
      {label ? label + " " : null}
      <b style={{ fontWeight: 500, color }}>{children}</b>
    </div>
  );
}
