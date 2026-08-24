"use client";

import { useEffect, useState } from "react";
import { Mark as Icon } from "../furniture/Mark";

/* ---------------------------------------------------------------------------
 * Shared collapse mechanism — design_handoff_agate/DESIGN.md § "Sections
 * Remember": collapse state persists per user under `dr:collapse:<section>`.
 * Default open on desktop, closed on mobile (≤700px) on first visit; an
 * explicit choice wins after that. Initializes after mount to avoid
 * SSR/hydration mismatches.
 *
 * This is the same mechanism `StandingsTable.tsx` implements inline (it
 * predates this file and isn't exported from there) — factored out here so
 * every other collapsible section (the trade scoreboard, and future
 * franchise-page sections) uses one implementation instead of a third copy.
 * ------------------------------------------------------------------------ */

/* NOTE: `components/methodology/MethodologySection.tsx` deliberately does NOT
 * use this hook. It gates its breakpoint in CSS instead, because resolving the
 * width in an effect would paint the whole methodology page expanded and then
 * collapse it under the reader; and it does not persist, because a reference
 * doc should open the same way every visit. Its header argues both. If you
 * change the SSR default or the persistence here, read that file too — the two
 * are the only collapse implementations in the app and they answer the same
 * question differently on purpose. */
export function useSectionCollapse(section: string) {
  const key = `dr:collapse:${section}`;
  const [open, setOpen] = useState(true); // SSR + first paint: desktop default

  useEffect(() => {
    let initial = true;
    try {
      const stored = window.localStorage.getItem(key);
      if (stored === "open") initial = true;
      else if (stored === "closed") initial = false;
      else initial = !window.matchMedia("(max-width: 700px)").matches;
    } catch {
      // localStorage unavailable — keep the desktop default.
    }
    setOpen(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(key, next ? "open" : "closed");
      } catch {
        // ignore — private mode etc.
      }
      return next;
    });
  };

  return { open, toggle };
}

/** Section header — role="button", 44px tap target, open/closed mark. Toggles
 *  collapse.
 *
 *  THERE IS NO SCOPE NOTE, and the prop is gone rather than optional so it
 *  cannot come back one call site at a time. The head used to carry a mono line
 *  at the right margin — "Cumulative · started points", the lens tally, a
 *  young/aging count. At desktop width they floated so far from the heading
 *  they read as unrelated page furniture, and each one restated something the
 *  section already showed: the metric control sits inches away, the tally is
 *  the ledger underneath, the counts are the two ledgers' own row counts.
 *  `StandingsTable.tsx` reached the same conclusion for its own inline copy —
 *  see the longer argument there, including the accessible-name bug that came
 *  of putting the note inside the button. */
export function SectionHeader({
  title, open, onToggle,
}: { title: string; open: boolean; onToggle: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-expanded={open}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
      className="tap flex items-baseline border-b border-rule pt-5 pb-1.5 cursor-pointer select-none"
    >
      <span className="flex items-baseline gap-2">
        <Icon name={open ? "open" : "closed"} size={12} className="text-dim" />
        <span className="font-display text-section font-bold tracking-[-0.024em]">{title}</span>
      </span>
    </div>
  );
}
