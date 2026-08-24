import type { ReactNode } from "react";

/* ---------------------------------------------------------------------------
 * Emphasis — one marked span inside a paragraph of prose.
 *
 * Named `Emphasis` and not `Mark` because `Mark` is already this system's icon
 * primitive (the nineteen stroked `fx-icon-paths`), and two things called Mark
 * beside each other in `furniture/` is one import away from the wrong one.
 *
 * WHY COLOUR IS ALLOWED HERE, AND ONLY HERE, AND ONLY IN TWO PLACES
 * ---------------------------------------------------------------------------
 * The house rule is that colour never carries information the words do not.
 * `good`/`risk` do not break it — they FOLLOW VALENCE. `--pos-strong` and
 * `--neg-strong` are the same pair the grade letter and the contribution bars
 * already use, so a green phrase in this paragraph means what a green letter
 * means two lines above it, and the phrase itself already says which it is. The
 * colour is a second reading of a fact the sentence carries, never the only
 * carrier of one.
 *
 * That is also the reason there is no fifth mark and no other hue:
 *
 *  - COBALT (`--stamp`) was proposed and rejected. Stamp is a GROUND you
 *    reverse type out of, it has five sanctioned slots, and one of them is the
 *    link colour — a blue unclickable word invites a click that does nothing.
 *  - `--warn` has no valence to follow. "Notable" is not a direction.
 *  - Anything else would be colour standing in for a category, which is the
 *    rule itself.
 *
 * So the two non-valence marks separate themselves by FACE and WEIGHT instead:
 * a figure takes Geist Mono (the face that sets every number in the product
 * already, applied inside prose rather than invented for it) plus a `--rule`
 * hairline as a second mark; a person takes the prose face at weight alone.
 * Adding a fifth colour is a design decision that goes through `.design/`, not
 * a value added to the union below.
 *
 * `-strong`, not the base pair: `--pos`/`--neg` are tuned for 10-13px mono
 * figures and drop below AA as text on every light ground this app uses. See
 * the `tone-contrast` rule in `tests/furniture-rules.test.ts` for the measured
 * ratios.
 * ------------------------------------------------------------------------ */

export const EMPHASIS_KINDS = ["num", "who", "good", "risk"] as const;

export type EmphasisKind = (typeof EMPHASIS_KINDS)[number];

/** Narrows an untrusted string — a mark name off a cached blurb, say — to a
 *  kind this component can render. Anything else is not a "wrong colour", it is
 *  plain prose, which is how an unknown mark degrades everywhere on this path. */
export function isEmphasisKind(v: unknown): v is EmphasisKind {
  return typeof v === "string" && (EMPHASIS_KINDS as readonly string[]).includes(v);
}

const TREATMENT: Record<EmphasisKind, string> = {
  // The hairline sits 1px under the baseline — see the leading note wherever
  // this is set in a paragraph; at a tight leading it crowds descenders on the
  // line below.
  num: "font-mono text-figure font-semibold text-ink tabular border-b-[1.5px] border-rule pb-px",
  who: "font-sans font-semibold text-ink",
  good: "font-semibold text-pos-strong",
  risk: "font-semibold text-neg-strong",
};

export function Emphasis({
  kind,
  children,
  className = "",
}: {
  kind: EmphasisKind;
  children: ReactNode;
  className?: string;
}) {
  return <span className={`${TREATMENT[kind]} ${className}`}>{children}</span>;
}
