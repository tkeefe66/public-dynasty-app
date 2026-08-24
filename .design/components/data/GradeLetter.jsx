import React from "react";

/* franchiseLetterTone(): A=pos, B=ink, C=ink/70, D=neg/78, F=neg.
   Deliberately --pos-strong / --neg-strong, not --pos / --neg: at this size on
   a pale identity tint --pos measures 2.90:1 and misses the 3:1 large-text
   floor. The ramp is the same on paper, in the rail and in the standings, so
   the same glyph always means the same thing. */
const TONE = {
  A: "var(--pos-strong)",
  B: "var(--ink)",
  C: "color-mix(in srgb, var(--ink) 70%, transparent)",
  D: "color-mix(in srgb, var(--neg-strong) 78%, transparent)",
  F: "var(--neg-strong)",
};

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
 * A franchise grade. The one place a letter carries colour, and the reason the
 * strong pair exists at all.
 */
export function GradeLetter({ grade, size = 44, style }) {
  const key = String(grade || "").trim().charAt(0).toUpperCase();
  return (
    <span
      style={{
        fontFamily: "var(--font-display)",
        fontWeight: 800,
        fontSize: px(size, 44),
        letterSpacing: "-.03em",
        lineHeight: 1,
        color: TONE[key] || "var(--ink)",
        ...style,
      }}
    >
      {grade}
    </span>
  );
}
