/* ---------------------------------------------------------------------------
 * Furniture port of `agate/IndeterminateBar.tsx` (`.design/components/
 * feedback/IndeterminateBar.jsx` + its prompt) — still the system's ONLY
 * animated element, still exactly ONE per view: an indeterminate segment
 * sliding on a hairline track. The `@keyframes indeterminate` this uses
 * already lives in `web/app/globals.css` (`translateX(-100%)` to
 * `translateX(400%)`) — declared once, reused here, never redefined.
 * `motion-reduce:animate-none` is belt-and-suspenders: globals.css already
 * zeroes every animation duration under `prefers-reduced-motion`.
 *
 * Track changed shape from the Agate original on purpose. Agate drew a
 * bordered, hollow box (`border border-rule`, no fill) because a stroke was
 * the only line weight the system had. Furniture has a hairline rhythm
 * token, so the track is now a FILLED `--rule` bar rather than an outline —
 * closer to the `.design` source's `height: 2, background: var(--rule)` and
 * more legible at the segment's small scale.
 *
 * The segment stays `bg-ink`, not `bg-stamp` as the `.design` mock has it.
 * Stamp has exactly five sanctioned slots under Furniture (primary button
 * fill, active segment/tab cell, link, focus ring, the "you" row marker) and
 * a loading indicator is not one of them — a sixth use needs a named entry
 * in `.design/tokens/stamp.css` through design review, not a quiet copy from
 * the mock.
 * ------------------------------------------------------------------------ */

export function IndeterminateBar({
  label,
  className = "",
}: {
  /** Optional caption rendered above the track (e.g. "Loading league history"). */
  label?: string;
  className?: string;
}) {
  return (
    <div className={className}>
      {label && (
        <div className="mb-1.5 font-mono text-label uppercase tracking-[0.14em] text-dim">
          {label}
        </div>
      )}
      <div
        role="progressbar"
        aria-label={label ?? "Loading"}
        className="relative h-0.5 overflow-hidden bg-rule"
      >
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-1/4 bg-ink motion-reduce:animate-none animate-[indeterminate_1.4s_ease-in-out_infinite]"
        />
      </div>
    </div>
  );
}
