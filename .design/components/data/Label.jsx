import React from "react";

/**
 * A mono uppercase label at 8.5px — the type floor. Nothing in the system is
 * set smaller, including the caption under a headline figure.
 *
 * Mono uppercase survives the remodel for labels ONLY. A heading is mixed
 * case; caps at heading size are the Agate voice.
 */
export function Label({ children, tone = "dim", size = "var(--text-label)", style }) {
  const color = tone === "ink" ? "var(--ink)" : tone === "stamp" ? "var(--stamp)" : "var(--dim)";
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: size,
        letterSpacing: ".14em",
        textTransform: "uppercase",
        color,
        ...style,
      }}
    >
      {children}
    </span>
  );
}

/** A slightly larger label that opens a block: "week 14 recap". */
export function Kicker({ children, style }) {
  return (
    <div style={{ fontFamily: "var(--font-mono)", fontSize: "9.5px", letterSpacing: ".15em", textTransform: "uppercase", color: "var(--dim)", ...style }}>
      {children}
    </div>
  );
}
