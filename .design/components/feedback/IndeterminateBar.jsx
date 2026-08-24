import React from "react";

/**
 * The only animated element in the system: one indeterminate segment on a
 * hairline track, ONE per view. No spinners, no shimmer, no pulsing dot —
 * animate-pulse is banned by name in the app's drift guard.
 *
 * The keyframes live in tokens/base.css so the animation is declared once.
 */
export function IndeterminateBar({ label, style }) {
  return (
    <div style={{ display: "grid", gap: 7, ...style }}>
      {label ? (
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-label)", letterSpacing: ".14em", textTransform: "uppercase", color: "var(--dim)" }}>{label}</span>
      ) : null}
      <span role="progressbar" aria-label={label || "Loading"} style={{ display: "block", height: 2, background: "var(--rule)", overflow: "hidden" }}>
        <span className="animate-indeterminate" style={{ display: "block", height: "100%", width: "25%", background: "var(--stamp)" }} />
      </span>
    </div>
  );
}
