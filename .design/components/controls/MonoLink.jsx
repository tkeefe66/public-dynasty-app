import React from "react";

/**
 * The app's affordance for "out to a bigger view" (PastPicksTable.tsx): mono,
 * 10px, uppercase, dim, underlined, ink on hover. Deliberately NOT a button —
 * a second filled control beside a real one dilutes the primary action.
 */
export function MonoLink({ children, href = "#", onClick, style, ...rest }) {
  return (
    <a
      href={href}
      onClick={onClick}
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: ".1em",
        textTransform: "uppercase",
        color: "var(--dim)",
        textDecoration: "underline",
        textUnderlineOffset: 3,
        ...style,
      }}
      {...rest}
    >
      {children}
    </a>
  );
}
