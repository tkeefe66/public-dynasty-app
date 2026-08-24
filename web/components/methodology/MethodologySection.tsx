"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Mark } from "@/components/furniture/Mark";
import { SectionHead } from "@/components/furniture/SectionHead";

/* ---------------------------------------------------------------------------
 * One methodology section, with two heads and one body.
 *
 * WHY TWO HEADS. The desktop page is a `Contents` rail beside the prose, and a
 * rail needs a second column that a 390px phone does not have. So on a phone the
 * eight sections become an accordion — collapsed by default, the title a 44px
 * disclosure row — and the contents *become* the page. Above 700px nothing
 * changes: the rail returns and every section is expanded prose, exactly as
 * before.
 *
 * WHY NOT `furniture/SectionCollapse`'s `useSectionCollapse`. That hook exists
 * precisely so there is not another copy of this mechanism, and this file IS
 * another copy — so the divergence has to be argued, not just committed.
 *
 * Two reasons it cannot be reused here as-is:
 *
 *   1. It resolves the breakpoint in an EFFECT (`useState(true)`, then a
 *      `matchMedia` read on mount). That is exactly the flash this component is
 *      built to avoid: on a phone the whole eight-section wall would paint
 *      expanded and then snap shut. Everywhere else the hook is used, the
 *      section is short and the flash is invisible; here it is the entire page.
 *   2. It persists to `localStorage` under `dr:collapse:<section>`, the design
 *      system's "Sections Remember" rule.
 *
 * (2) IS A DELIBERATE DEVIATION, not an oversight: this page is reference
 * documentation, and remembering that section 7 was open a week ago is worse
 * than a predictable cold start — you come back to a doc to read it from the
 * top. If that judgement is ever reversed, the fix is a persisted key here, not
 * a rewrite onto the hook, because (1) still applies.
 *
 * WHY THE BREAKPOINT IS CSS AND NOT `matchMedia`. The obvious build is one head
 * chosen in JS. It cannot work here without a flash: the server has no width, so
 * it must guess, and whichever it guesses is wrong for half the traffic — on a
 * phone that means the entire 8-section wall painting and then snapping shut
 * under the reader's thumb. Gating in CSS renders the right shape on the first
 * paint at every width, with no hydration step in the middle.
 *
 * The cost is that the title string appears twice in the markup. Only the title:
 * the body — all the prose, panels and arithmetic — is rendered exactly once and
 * shared by both heads. Each head is `display: none` at the other's width, which
 * takes it out of the accessibility tree AND out of the tab order, so a screen
 * reader sees one heading per section and a keyboard user finds one control.
 * `tabindex` cannot be set from a media query, which is precisely why the single
 * always-rendered button was rejected: on desktop it would be a focusable
 * control announcing "collapsed" over content that is permanently visible.
 *
 * `min-[701px]:` is the app's mobile boundary, matching `RatingBars.tsx`, which
 * drops the bar column at the same width.
 * ------------------------------------------------------------------------ */

export function MethodologySection({
  id,
  title,
  kicker,
  children,
}: {
  /** The section's anchor. Deep links point here, so it never changes. */
  id: string;
  title: string;
  /** Optional short count, mono, on the right of the disclosure row. It must
   *  reconcile with what is actually inside — derive it, never type it. */
  kicker?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const bodyId = `${id}-body`;

  /* A deep link into a collapsed section has to open it, or the anchor resolves
   * to a heading with nothing under it. Runs on mount for a cold load and on
   * `hashchange` for a same-page jump (the rail's own links, at widths where
   * both exist). Scrolling again after the open is deliberate: the browser
   * already scrolled while the body was still `display: none`, so its first
   * attempt landed at the wrong offset. */
  useEffect(() => {
    const openIfTargeted = () => {
      if (window.location.hash !== `#${id}`) return;
      setOpen(true);
      requestAnimationFrame(() => {
        document.getElementById(id)?.scrollIntoView?.();
      });
    };
    openIfTargeted();
    window.addEventListener("hashchange", openIfTargeted);
    return () => window.removeEventListener("hashchange", openIfTargeted);
  }, [id]);

  return (
    <section id={id} className="scroll-mt-20">
      {/* ≥701px: the section head as it has always been set. */}
      <div className="hidden min-[701px]:block">
        <SectionHead title={title} />
      </div>

      {/* ≤700px: the same title as a disclosure. Wrapped in the heading it
          replaces, so the document outline survives the swap — the WAI-ARIA
          accordion shape (heading > button). Mixed case, like every Furniture
          heading; the kicker is mono and keeps its caps. */}
      <h2 className="min-[701px]:hidden">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((prev) => !prev)}
          className="tap flex w-full select-none items-center gap-2.5 border-b border-rule py-2 text-left"
        >
          <Mark name={open ? "open" : "closed"} size={12} className="text-dim" />
          <span className="min-w-0 flex-1 font-display text-section font-bold tracking-[-0.024em]">
            {title}
          </span>
          {/* aria-hidden: the kicker is visual reinforcement, and without this
              the accessible name is width-dependent — "The verdict 13 bands" on
              a phone against "The verdict" on a desktop, for the same heading in
              the same document. The desktop head shows no kicker either, so
              hiding it from the name is what makes the two widths agree. The
              figures are all derived and restated inside the section anyway. */}
          {kicker && (
            <span
              aria-hidden="true"
              className="shrink-0 font-mono text-label uppercase tracking-[0.11em] text-dim"
            >
              {kicker}
            </span>
          )}
        </button>
      </h2>

      {/* One body, two behaviours. Closed is the ≤700px default and the reason
          `useState(false)` is safe to render on the server: at ≥701px
          `min-[701px]:block` overrides `hidden`, so the desktop body is open
          whatever the state says, and the state only ever governs the phone. */}
      <div
        id={bodyId}
        className={`pb-10 min-[701px]:pb-0 ${open ? "" : "hidden min-[701px]:block"}`}
      >
        {children}
      </div>
    </section>
  );
}
