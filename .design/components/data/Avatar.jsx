import React from "react";

/* px() — an attribute value is a STRING, and React only unit-suffixes NUMBERS.
   size="78" from a template arrives as "78", React emits invalid CSS, and the
   property is dropped: the glyph silently falls back to the inherited size.
   Coerced here rather than at the call site, because a consuming project will
   write size="78" too. A string that already carries a unit passes through. */
const px = (v, fallback) => {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = parseFloat(v);
    return Number.isNaN(n) ? v : n;   // "30px" -> 30, so arithmetic still works
  }
  return fallback;
};

/**
 * A franchise's identity mark: its colour, with an initial. This and the 5px
 * hero edge are the only places identity colour appears — never a figure, a
 * bar or a chart series.
 */
export function Avatar({ name = "", color = "var(--id-2)", size = 36, style }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: px(size, 36),
        height: px(size, 36),
        borderRadius: "var(--radius-sm)",
        background: color,
        display: "grid",
        placeItems: "center",
        fontFamily: "var(--font-display)",
        fontWeight: 800,
        fontSize: Math.round(px(size, 36) * 0.39),
        color: "#14151a",
        flex: "none",
        ...style,
      }}
    >
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
