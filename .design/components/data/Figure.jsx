import React from "react";

/* U+2212 MINUS SIGN, never toLocaleString's U+002D hyphen-minus: in a
   tabular-nums column the two differ in width and vertical position, and a
   card showing a hyphen headline above a true-minus meta line reads as two
   different kinds of number. This is the system's single source for the glyph
   — anything parsing these strings back must normalise it. */
const MINUS = "\u2212";
const fmt = (v, dp) => {
  if (typeof v !== "number") return v;
  const s = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return v < 0 ? MINUS + s : s;
};

/**
 * Every number in the app. Geist Mono, tabular, right-aligned by default so
 * columns line up digit-for-digit.
 *
 * Colour belongs to SIGNED values only — an unsigned figure is always ink, and
 * zero or absent is --dim. The pair used here is --pos/--neg, which is tuned
 * for 10-13px mono on paper; a LARGE glyph needs --pos-strong/--neg-strong
 * instead (see GradeLetter), and a BAR needs --pos-bar/--neg-bar. Three pairs,
 * not interchangeable.
 */
export function Figure({
  value,
  signed = false,
  dp = 0,
  size = "var(--text-figure)",
  align = "right",
  dim = false,
  suffix,
  style,
}) {
  const empty = value == null || value === "";
  const n = typeof value === "number" ? value : NaN;
  const zero = n === 0;
  const color =
    empty || zero || dim
      ? "var(--dim)"
      : signed && !Number.isNaN(n)
      ? n > 0
        ? "var(--pos)"
        : "var(--neg)"
      : "var(--ink)";

  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontVariantNumeric: "tabular-nums",
        fontSize: size,
        fontWeight: signed && !empty && !zero ? 600 : 400,
        textAlign: align,
        color,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {empty ? "\u2014" : `${signed && n > 0 ? "+" : ""}${fmt(value, dp)}`}
      {suffix ? <span style={{ color: "var(--dim)" }}> {suffix}</span> : null}
    </span>
  );
}
