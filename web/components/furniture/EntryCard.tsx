import type { ComponentPropsWithoutRef, ReactNode } from "react";

/**
 * One entry as a card — what a ledger row becomes at or below 700px.
 *
 * This is the decided answer to the mobile split, not an alternative to it: on
 * a phone a card's EDGE is the entry boundary, so narrow layouts are never
 * solved with border logic and no column is ever hidden behind a sideways
 * scroll. Every column survives; it just stacks.
 *
 * It replaces Agate's multi-rule entry — `className="ruled block"` with
 * `borderTopWidth: 0`, a block that carried the striped ground itself so two or
 * three rules read as one tap target. A card needs none of that: it is one box,
 * so it is one target by construction.
 *
 * Renders an `<a>` when `href` is given, so the whole card is the link.
 */
export function EntryCard({
  href,
  variant = "body",
  className = "",
  children,
  ...rest
}: Omit<ComponentPropsWithoutRef<"a">, "href"> & {
  href?: string;
  variant?: "body" | "mine";
  children?: ReactNode;
}) {
  const cls =
    "block rounded-panel border border-rule-strong bg-surface px-3.5 py-3 " +
    "font-mono text-figure tabular text-dim no-underline " +
    (variant === "mine" ? "border-l-[3px] border-l-stamp bg-stamp-wash pl-[11px] " : "") +
    className;
  if (href) {
    return (
      <a href={href} className={cls} {...rest}>
        {children}
      </a>
    );
  }
  return <div className={cls}>{children}</div>;
}

/**
 * The card stack. Gapped rather than margined, so the spacing belongs to the
 * list and a card can be moved between lists without carrying its own margin.
 */
export function CardList({
  className = "",
  children,
  ...rest
}: ComponentPropsWithoutRef<"div">) {
  // Forwards `...rest` so a caller can name the list for assistive tech
  // (`role="group"` + `aria-labelledby`) or hang a `data-testid` on it. Without
  // this, callers wrapped the list in an extra div purely to carry one
  // attribute — which is a layout node existing for a non-layout reason.
  return (
    <div className={`flex flex-col gap-[var(--gap)] ${className}`} {...rest}>
      {children}
    </div>
  );
}

/**
 * A card's secondary facts, under a single hairline.
 *
 * ONE rule, at the top of the whole block — never between the facts. A divider
 * drawn between an entry's own children is what `EntryCard` exists to avoid:
 * it reads at the same weight as the boundary between entries and, in
 * `EntryCard.prompt.md`'s words, "cut a franchise in half". The card's edge is
 * the entry boundary; this hairline only separates headline from detail.
 *
 * Each fact wraps as a WHOLE unit (`Meta` is `nowrap`), because a broken
 * "2nd · peaking" reads as two facts rather than one.
 */
export function MetaLine({
  className = "",
  children,
  ...rest
}: ComponentPropsWithoutRef<"div">) {
  // Forwards `...rest` for the same reason `CardList` does: a caller needs to
  // hang a `data-testid` or an aria attribute on the line itself, and without
  // it the only alternative is wrapping the line in a div that exists for a
  // non-layout reason. It also makes a fact COUNT testable — asserting on
  // textContent cannot do that reliably (`\bReg\b` silently never matches when
  // the preceding character is a digit, which is how a trimmed-facts test
  // passed against a card that still had six).
  return (
    <div
      className={`flex flex-wrap gap-x-3.5 gap-y-1.5 border-t border-rule pt-2.5 ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * One labelled fact in a `MetaLine`.
 *
 * `tone` colours the VALUE only — the label stays dim. That is the same rule
 * the ledger figures follow: colour marks a signed outcome, never a category,
 * and a coloured label would make the category itself look like a result.
 *
 * THE `-strong` PAIR, and the contrast math is why. `--text-figure` is 12.5px,
 * which is NORMAL text under WCAG (the large-text exemption starts at 18.66px
 * bold / 24px), so the bar is 4.5:1. Measured against the real token values on
 * a card's `--surface`:
 *
 *     --pos  #00a63e  3.22:1  FAILS      --pos-strong  #007a33  5.48:1  passes
 *     --neg  #e12d39  4.53:1  passes     --neg-strong  #a3131d  7.87:1  passes
 *
 * This briefly shipped as the base pair, on the strength of `colors.css`'s note
 * that the strong half is for "large tone-ramped glyphs ONLY … never for a row
 * figure". That note over-claims: it defends a real point (do not darken a row
 * figure into ink) but generalises it into a rule that leaves NO compliant
 * green anywhere, because the base pair misses AA on both grounds. Contrast
 * wins over the aesthetic note. Logged upstream.
 */
export function Meta({
  label,
  tone,
  className = "",
  children,
}: {
  label?: string;
  tone?: "pos" | "neg" | "dim";
  className?: string;
  children?: ReactNode;
}) {
  // "dim" is a real tone, not the absence of one. A signed figure at zero must
  // read dim — "sign is always rendered; zero or an absent value is --dim,
  // never invent a sign for zero" — and without this it fell through to
  // full-weight ink, which reads as a result rather than as nothing.
  const value =
    tone === "pos" ? "text-pos-strong"
    : tone === "neg" ? "text-neg-strong"
    : tone === "dim" ? "text-dim"
    : "text-ink";
  return (
    <span className={`whitespace-nowrap font-mono text-figure tabular text-dim ${className}`}>
      {label ? `${label} ` : null}
      <b className={`font-medium ${value}`}>{children}</b>
    </span>
  );
}
