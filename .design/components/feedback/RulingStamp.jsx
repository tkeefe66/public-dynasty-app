import React from "react";

/**
 * A trade ruling, stamped. The verdict IS the headline — the reason this reads
 * as a ruling rather than a table is that the winner and the margin come
 * first, and the lens-by-lens detail sits underneath in a Panel.
 *
 * The stamp ground is one of the second ink's five sanctioned places. Agate
 * drew this with a 2px band-opening rule and no radius; here it is the same
 * ground with the one radius, like every other object.
 */
export function RulingStamp({ verdict, winner, detail, tag, style }) {
  return (
    <div style={{ background: "var(--stamp)", color: "var(--stamp-ink)", borderRadius: "var(--radius)", padding: "16px 18px", display: "grid", gap: 8, ...style }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 8.5, letterSpacing: ".15em", textTransform: "uppercase", opacity: 0.74 }}>{verdict || "Ruling"}</span>
      <span style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 25, letterSpacing: "-.03em", lineHeight: 1.05 }}>{winner}</span>
      {detail ? <span style={{ fontSize: 12.5, lineHeight: 1.5, opacity: 0.92 }}>{detail}</span> : null}
      {tag ? (
        <span style={{ marginTop: 2, paddingTop: 9, borderTop: "1px solid rgba(255,255,255,.28)", fontFamily: "var(--font-mono)", fontSize: 8.5, letterSpacing: ".15em", textTransform: "uppercase", opacity: 0.85 }}>{tag}</span>
      ) : null}
    </div>
  );
}
