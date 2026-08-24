"use client";

import { useState, useRef, useEffect, useLayoutEffect, useId } from "react";
import { createPortal } from "react-dom";
import { Mark as Icon } from "./furniture/Mark";

interface Props {
  title: string;
  body: string;
  formula?: string;
  align?: "left" | "right";
}

const WIDTH = 288; // matches w-72
const MARGIN = 8; // keep this far from the viewport edge

export function InfoTooltip({ title, body, formula, align = "left" }: Props) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const tooltipId = useId();

  // Portal target (document.body) only exists client-side.
  useEffect(() => setMounted(true), []);

  // Position relative to the viewport so the popover escapes any ancestor
  // overflow. The horizontal scroll containers and overflow-hidden cards that
  // originally clipped it are retired with the Agate port, but a `.ruled` row is
  // still a fixed 26px box, so viewport placement stays the right call.
  const place = () => {
    const el = btnRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    let left = align === "right" ? r.right - WIDTH : r.left;
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - WIDTH - MARGIN));
    setPos({ top: r.bottom + 6, left });
  };

  useLayoutEffect(() => {
    if (open) place();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Keep it pinned to the icon if the page scrolls/resizes while open.
  useEffect(() => {
    if (!open) return;
    const onMove = () => place();
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <span className="relative inline-block">
      {/* p/-m gives a ≥24px tap target (WCAG 2.5.8) around the 12px glyph
          without shifting surrounding layout. Hover opens on pointer devices;
          tap/Enter toggles on touch + keyboard. */}
      <button
        ref={btnRef}
        type="button"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) { setOpen(false); }
        }}
        className="inline-flex items-center justify-center p-[5px] -m-[5px] align-middle text-dim hover:text-ink"
        aria-label={`info: ${title}`}
        aria-expanded={open}
        aria-describedby={open ? tooltipId : undefined}
      >
        {/* Agate — the trigger is the `info` mark (a square with the "i" cut
            into it), not a circled "i" (DESIGN.md § "No Icon Library, But
            There Is A Set"). */}
        <Icon name="info" size={12} />
      </button>
      {/* Agate — Floating Layers (DESIGN.md § "Named rules"): `--bg` panel,
          1px ink border, no radius, no shadow. Popovers get NO backdrop
          field. 120ms opacity reveal, reduced-motion neutralized globally. */}
      {mounted && open &&
        createPortal(
          <span
            id={tooltipId}
            role="tooltip"
            className="animate-tip-in pointer-events-none fixed z-50 w-72 rounded-sm border border-ink bg-bg text-ink"
            style={{ top: pos.top, left: pos.left }}
          >
            <span className="block px-2.5 pt-2 font-mono text-label uppercase tracking-[0.14em] text-dim">
              {title}
            </span>
            <span className="block px-2.5 pb-2.5 pt-1 text-figure leading-relaxed text-body">{body}</span>
            {formula && (
              <span className="block border-t border-rule bg-rule-lit px-2.5 py-1.5 font-mono text-figure text-ink">
                {formula}
              </span>
            )}
          </span>,
          document.body,
        )}
    </span>
  );
}
