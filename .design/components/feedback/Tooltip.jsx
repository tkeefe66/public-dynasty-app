import React from "react";
import { Mark } from "../controls/Mark.jsx";

/**
 * The definition behind a label (InfoTooltip.tsx). A signal named "Draft Skill"
 * is meaningless on its own, so every pillar and signal carries one — a row of
 * triggers with no definitions attached is worse than no triggers at all.
 *
 * The trigger is the "info" mark, NOT a circled "?" — DESIGN.md § "No Icon
 * Library, But There Is A Set".
 *
 * TWO THINGS THAT MUST HOLD. The panel is positioned against the VIEWPORT: a
 * Panel clips to its radius with overflow:hidden, so a tooltip laid out inside
 * one is cut off. And the 26px target is deliberate — this is the one control
 * below the 44px floor, because it lives inside a 34px contribution rule where
 * a 44px target would overflow the row. 26px clears WCAG 2.5.8's 24px minimum
 * and matches the app's own p-[5px] -m-[5px] on a 12px icon. Do not "fix" it.
 */
export function Tooltip({ title, body, formula, children, style }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  const [pos, setPos] = React.useState({ top: 0, left: 0 });

  const place = React.useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const width = 288, margin = 8;
    setPos({ top: r.bottom + 6, left: Math.max(margin, Math.min(r.left, window.innerWidth - width - margin)) });
  }, []);

  React.useEffect(() => {
    if (!open) return;
    place();
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    document.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, place]);

  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-expanded={open}
        aria-label={title ? "About " + title : "More information"}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          flex: "none",
          padding: 7,
          margin: -7,
          background: "none",
          border: 0,
          color: open ? "var(--ink)" : "var(--dim)",
          cursor: "help",
          ...style,
        }}
      >
        {children || <Mark name="info" size={12} />}
      </button>
      {open ? (
        <span
          role="tooltip"
          style={{
            position: "fixed",
            top: pos.top,
            left: pos.left,
            zIndex: 90,
            width: 288,
            background: "var(--surface)",
            borderRadius: "var(--radius-sm)",
            boxShadow: "0 2px 6px rgba(20,21,26,.08), 0 14px 34px -12px rgba(20,21,26,.3)",
            overflow: "hidden",
            pointerEvents: "none",
          }}
        >
          {title ? (
            <span style={{ display: "block", padding: "9px 11px 0", fontFamily: "var(--font-mono)", fontSize: 8, letterSpacing: ".14em", textTransform: "uppercase", color: "var(--dim)" }}>{title}</span>
          ) : null}
          <span style={{ display: "block", padding: "4px 11px 10px", fontFamily: "var(--font-sans)", fontSize: 11.5, lineHeight: 1.6, color: "var(--body)" }}>{body}</span>
          {formula ? (
            <span style={{ display: "block", padding: "7px 11px", borderTop: "1px solid var(--rule)", background: "var(--surface-sunk)", fontFamily: "var(--font-mono)", fontSize: 10, fontVariantNumeric: "tabular-nums", color: "var(--ink)" }}>{formula}</span>
          ) : null}
        </span>
      ) : null}
    </>
  );
}
