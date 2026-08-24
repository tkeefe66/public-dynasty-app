import React from "react";

/**
 * The masthead. A full stamp ground with type reversed out of it — one of the
 * five sanctioned places for the second ink, and the only one that is a large
 * area. Never a tint: stamp is a ground, and a stamp-coloured word sitting on
 * paper is the thing this system does not do.
 */
export function StampBand({ kicker, title, meta, children, style }) {
  return (
    <div
      style={{
        background: "var(--stamp)",
        color: "var(--stamp-ink)",
        borderRadius: "var(--radius)",
        padding: "22px 24px 24px",
        ...style,
      }}
    >
      {kicker ? (
        <div style={{ fontFamily: "var(--font-mono)", fontSize: "9.5px", letterSpacing: ".15em", textTransform: "uppercase", opacity: 0.74 }}>
          {kicker}
        </div>
      ) : null}
      {title ? (
        <h1 style={{ margin: "8px 0 0", fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "var(--text-nameplate)", letterSpacing: "-.038em", lineHeight: 1 }}>
          {title}
        </h1>
      ) : null}
      {meta ? (
        <div style={{ marginTop: 10, fontFamily: "var(--font-mono)", fontSize: "var(--text-label)", letterSpacing: ".14em", textTransform: "uppercase", opacity: 0.74 }}>
          {meta}
        </div>
      ) : null}
      {children}
    </div>
  );
}
