import type { ReactNode } from "react";

/* ---------------------------------------------------------------------------
 * Furniture port of `agate/StateMessage.tsx` (`.design/components/feedback/
 * StateMessage.jsx` + its prompt). Same grammar as Agate's "Failure Is A
 * Headline": a mono kicker naming the condition, a headline in plain words,
 * one line of body, one action below it — never folded into the prose. That
 * grammar survives the remodel unchanged; only the type and colour did.
 *
 * Two things this file deliberately does NOT pick up from the .design mock:
 *   - The mock wraps the message in an elevated `--surface` card
 *     (`background`/`shadow`/`radius`). A state message sits IN the page
 *     flow — it is not a modal or a floater — so this stays un-panelled, as
 *     Agate's did. Elevation is available under Furniture now; that is not
 *     the same as this component needing it.
 *   - The mock's icon (`Mark`) isn't drawn here: `furniture/Mark` does not
 *     exist in this repo yet (the drift guard's `retired-primitives` rule
 *     notes the same gap for `agate/Icon`). Add the mark to this component
 *     in the same commit that adds `furniture/Mark`, not before.
 *
 * The heading is the one place the type change is loudest: Agate set it
 * Archivo 800 at a raw px size. Furniture sets it Bricolage `font-bold` at
 * the `text-section` scale step, in MIXED CASE — mono labels keep their
 * caps, headings do not. It also takes `text-ink` explicitly rather than
 * inheriting the section's ambient colour: a heading is the primary thing on
 * screen and must never quietly pick up `--dim` from a parent.
 *
 * Error voice is unchanged and non-negotiable: name the condition in the
 * kicker, then plain words. "Not you — us." Never "Oops."
 * ------------------------------------------------------------------------ */

interface Props {
  /** Mono uppercase condition label, e.g. "No leagues yet" / "Load failed". */
  kicker: string;
  /** Headline. Say what will appear here, not that something is missing. */
  headline: string;
  /** One line. Optional — a headline can carry the whole message. */
  body?: string;
  /** One action, rendered below the body (pass a furniture `Button`). */
  action?: ReactNode;
  /** Whether the condition is a failure — tints the kicker only. */
  tone?: "neutral" | "negative";
  className?: string;
}

export function StateMessage({
  kicker,
  headline,
  body,
  action,
  tone = "neutral",
  className = "",
}: Props) {
  return (
    <section className={className}>
      <div className="border-b border-rule pb-1.5">
        <span
          className={`font-mono text-label uppercase tracking-[0.12em] ${
            tone === "negative" ? "text-neg-strong" : "text-dim"
          }`}
        >
          {kicker}
        </span>
      </div>
      <div className="mt-3 font-display text-section font-bold leading-[1.1] tracking-[-0.03em] text-ink">
        {headline}
      </div>
      {body && <p className="mt-2 max-w-[52ch] text-prose leading-relaxed text-body">{body}</p>}
      {action && <div className="mt-3">{action}</div>}
    </section>
  );
}
