import React from "react";
import { Mark } from "./Mark.jsx";

/**
 * Light / Dark. A real control rather than a system-preference read, because
 * the dark ground is the one Sleeper's audience expects and choosing it is
 * part of the product's voice.
 */
export function ThemeToggle({ value = "light", onChange, style }) {
  return (
    <div style={{ display: "inline-flex", border: "1px solid var(--rule-strong)", borderRadius: "var(--radius-pill)", overflow: "hidden", ...style }}>
      {[["light", "Light"], ["dark", "Dark"]].map(([v, t]) => {
        const on = v === value;
        return (
          <button
            key={v}
            type="button"
            aria-pressed={on}
            onClick={() => onChange && onChange(v)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              background: on ? "var(--ink)" : "none",
              color: on ? "var(--bg)" : "var(--dim)",
              border: 0,
              padding: "6px 11px",
              minHeight: 30,
              fontFamily: "var(--font-mono)",
              fontSize: "8.5px",
              letterSpacing: ".12em",
              textTransform: "uppercase",
              cursor: "pointer",
            }}
          >
            <Mark name={v} size={11} />
            {t}
          </button>
        );
      })}
    </div>
  );
}
