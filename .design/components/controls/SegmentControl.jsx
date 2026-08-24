import React from "react";

/**
 * The app's ONE segmented-control dialect (SegmentControl.tsx) — every
 * single-select chip group: year and season filters, metric switches, view
 * toggles. If something switches a single-select view it is this, not a
 * bespoke pill.
 *
 * AN UNDERLINE RUN. Agate drew it as a 1px hard-cornered box with hairlines
 * between items. Furniture's first draft drew a PILL IN A WELL — a sunk track
 * with a stamp-filled pill riding in it, 38px of pill plus 3px of well each
 * side. That is 50px of chrome per control, and controls arrive in PAIRS: the
 * consuming app's production chart spent 120px on two of them plus their
 * whisper labels before drawing a single data point. The well and the pill are
 * both gone. Options sit as a plain mono run and the active one takes full ink
 * plus a 2px stamp underline.
 *
 * THE UNDERLINE IS THE POINT, not a weaker stamp. The rule this component has
 * always had — the active segment must invert, because a colour-only change
 * does not read — is a rule about SHAPE, and an underline is a change of shape.
 * It satisfies it at 24px instead of 50. Weight alone (bold among dim) would
 * not, which is why an inactive option keeps `--dim` rather than only losing
 * its bold.
 *
 * THE TAP TARGET IS STILL 44px. The visible run is ~24px; each option carries
 * a transparent absolutely-positioned box at -11px/-8px, so the hit area
 * clears the 44px floor while the ink stops claiming the height. Shrinking the
 * target along with the paint is the trap here — do not "simplify" that span
 * away, and do not reach for `minHeight: 44`, which puts the 44px back into
 * the layout box and gives the row its height back.
 *
 * The selection mark is always rendered and merely transparent when inactive,
 * so switching cannot reflow the run by a pixel.
 *
 * Wraps rather than scrolling — horizontal scroll is one of the patterns the
 * app's drift guard bans. Without the well a wrapped run costs two 24px lines
 * instead of two 50px rows, which is what makes a nine-season league
 * affordable.
 *
 * `--text-label` (8.5px), not the hardcoded `fontSize: 10` this file used to
 * carry: 10 is not on the seven-step scale, and a size off the list is a size
 * someone eyeballed.
 */
export function SegmentControl({ options, value, onChange, label, style }) {
  return (
    <div
      role="group"
      aria-label={label}
      style={{
        display: "inline-flex",
        flexWrap: "wrap",
        alignItems: "center",
        columnGap: 16,
        rowGap: 8,
        ...style,
      }}
    >
      {options.map((o) => {
        const v = typeof o === "string" ? o : o.value;
        const t = typeof o === "string" ? o : o.label;
        const on = v === value;
        return (
          <button
            key={v}
            type="button"
            aria-pressed={on}
            onClick={() => onChange && onChange(v)}
            style={{
              position: "relative",
              appearance: "none",
              background: "transparent",
              color: on ? "var(--ink)" : "var(--dim)",
              fontWeight: on ? 700 : 400,
              border: 0,
              padding: "3px 0",
              fontFamily: "var(--font-mono)",
              fontSize: "var(--text-label)",
              letterSpacing: ".08em",
              textTransform: "uppercase",
              cursor: "pointer",
            }}
          >
            {/* The 44px hit area, invisible. */}
            <span aria-hidden="true" style={{ position: "absolute", top: -11, right: -8, bottom: -11, left: -8 }} />
            {t}
            {/* The selection mark: a 2px stamp rule, zero radius. */}
            <span
              aria-hidden="true"
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                bottom: -3,
                height: 2,
                background: on ? "var(--stamp)" : "transparent",
              }}
            />
          </button>
        );
      })}
    </div>
  );
}
