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
 * A magnitude bar in a sunk track.
 *
 * This used to read "the same figure SegmentControl draws, so a control and a
 * bar read as two instances of one idea". That is no longer true: the segment
 * control lost its sunk well and is an underline run now, because the well
 * cost 50px per control. The sunk track stays HERE on its own merits — a bar
 * needs a trough to show the unfilled remainder against, which is a
 * requirement a control never had — so what changed is the cross-reference,
 * not the drawing.
 *
 * Signed bars use --pos-bar/--neg-bar, a THIRD pair: a bar is a large solid
 * area, so the two hues must be weight-matched or the louder one reads as
 * "more" at equal length. --neg is hotter than --pos and pulls green forward.
 *
 * A negative bar is SOLID and grows leftward from a centre line. A hollow
 * outline was tried and abandoned: at real magnitudes many bars are 3-8px
 * wide, where a 1.5px ring on each side leaves no interior at all.
 */
export function Bar({ value, max = 100, signed = false, height = 5, style }) {
  const h = px(height, 5);
  const pct = Math.min(100, (Math.abs(Number(value)) / Number(max)) * 100);
  const neg = value < 0;
  const fill = signed ? (neg ? "var(--neg-bar)" : "var(--pos-bar)") : "var(--ink)";
  if (!signed) {
    return (
      <span style={{ display: "block", height: h, borderRadius: 3, background: "var(--rule)", overflow: "hidden", ...style }}>
        <span style={{ display: "block", height: "100%", width: pct + "%", borderRadius: 3, background: fill }} />
      </span>
    );
  }
  return (
    <span style={{ display: "block", position: "relative", height: h, borderRadius: 3, background: "var(--rule)", ...style }}>
      <span style={{ position: "absolute", left: "50%", top: -1, bottom: -1, width: 1, background: "var(--rule-strong)" }} />
      <span
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          borderRadius: 3,
          background: fill,
          width: pct / 2 + "%",
          ...(neg ? { right: "50%" } : { left: "50%" }),
        }}
      />
    </span>
  );
}
