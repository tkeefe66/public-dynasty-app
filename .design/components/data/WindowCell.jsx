import React from "react";

/* WINDOW_STAGES (lib/window.ts) is an ORDERED five-step sequence, low strength
   and trajectory to high — not four quadrants. Rendering it as a scatter plot
   was the wrong diagram: it made an ordered position look like a coordinate. */
const STAGES = ["Rebuilding", "Retooling", "Competing", "Contending", "Dynasty"];

/**
 * One franchise's competitive window, as a position on the ladder. The active
 * cell inverts to the stamp; the others are a sunk track.
 */
export function WindowCell({ stage, style }) {
  const i = STAGES.indexOf(stage);
  return (
    <div style={{ display: "flex", gap: 2, background: "var(--surface-sunk)", borderRadius: "var(--radius-pill)", padding: 3, ...style }}>
      {STAGES.map((s, n) => {
        const on = n === i;
        return (
          <span
            key={s}
            title={s}
            style={{
              flex: 1,
              minHeight: 30,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "var(--radius-pill)",
              background: on ? "var(--stamp)" : "transparent",
              color: on ? "var(--stamp-ink)" : "var(--dim)",
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              fontWeight: on ? 700 : 400,
              letterSpacing: ".06em",
              textTransform: "uppercase",
              whiteSpace: "nowrap",
              padding: "0 8px",
            }}
          >
            {s}
          </span>
        );
      })}
    </div>
  );
}

export const WINDOW_STAGES = STAGES;
