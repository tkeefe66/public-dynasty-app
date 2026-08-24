import React from "react";

/**
 * A text input. One radius, a --rule-strong edge, and the stamp focus ring
 * from base.css. There is no filled or underlined variant.
 */
export function Field({ label, hint, id, style, ...rest }) {
  const inputId = id || (label ? "f-" + label.toLowerCase().replace(/[^a-z0-9]+/g, "-") : undefined);
  return (
    <label htmlFor={inputId} style={{ display: "block", ...style }}>
      {label ? (
        <span style={{ display: "block", fontFamily: "var(--font-mono)", fontSize: "var(--text-label)", letterSpacing: ".12em", textTransform: "uppercase", color: "var(--dim)", marginBottom: 6 }}>
          {label}
        </span>
      ) : null}
      <input
        id={inputId}
        style={{
          width: "100%",
          boxSizing: "border-box",
          background: "var(--surface)",
          border: "1px solid var(--rule-strong)",
          borderRadius: "var(--radius-sm)",
          padding: "11px 12px",
          minHeight: 44,
          fontFamily: "var(--font-sans)",
          fontSize: "var(--text-body)",
          color: "var(--ink)",
        }}
        {...rest}
      />
      {hint ? (
        <span style={{ display: "block", marginTop: 6, fontSize: 11.5, lineHeight: 1.5, color: "var(--dim)" }}>{hint}</span>
      ) : null}
    </label>
  );
}
