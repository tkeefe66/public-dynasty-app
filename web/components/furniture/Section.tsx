import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";
import { SectionHead } from "./SectionHead";

/* ---------------------------------------------------------------------------
 * The Furniture replacement for Agate's `Card`/`CardHead`.
 *
 * Agate deleted the card as a concept — "a section is a heading over a hairline,
 * then content", with no border, radius or fill — because it had no elevation
 * vocabulary at all. Furniture has one, but the answer here did not simply
 * revert: a *section* is still a heading over a hairline. What gained the panel
 * is the LEDGER inside it (`Panel`), not the section wrapper. Wrapping both puts
 * a box inside a box, which is the drift this system is most prone to.
 *
 * No directive on purpose: `ownerdeepdive/ui.tsx` is `"use client"`, and these
 * two presentational wrappers are needed from server components too. Keeping
 * them directive-free is why they live here rather than there.
 * ------------------------------------------------------------------------ */

/**
 * `...rest` is forwarded, matching `Row`, `EntryCard`, `CardList` and
 * `MetaLine`. It is not decoration: without it a caller writing
 * `<Section data-testid="…">` gets code that **type-checks, compiles and
 * builds**, and then silently drops the attribute at runtime — so a test
 * querying for it fails while the component renders perfectly. That cost a
 * debugging round in phase 5, and `Section` was the only primitive in this
 * directory that did not forward, which is exactly why it was the one that
 * bit. Do not remove it to "tidy the signature".
 */
export function Section({
  children,
  className = "",
  ...rest
}: {
  children: ReactNode;
  className?: string;
} & Omit<ComponentPropsWithoutRef<"section">, "className" | "children">) {
  return (
    <section className={`mb-6 ${className}`} {...rest}>
      {children}
    </section>
  );
}

/**
 * A section's heading. Mixed case — this is the single most visible type change
 * in the port, and re-adding `uppercase` here would undo it across the whole
 * franchise page at once.
 */
export function SectionTitle({
  title,
  right,
  filter,
  as,
}: {
  title: string;
  right?: ReactNode;
  /** A control over this section — rendered beside the title rather than at
   *  the far margin. See `SectionHead`'s note on the three slots. */
  filter?: ReactNode;
  /** Retained for callers that need h3 for document outline reasons. */
  as?: ElementType;
}) {
  return (
    <SectionHead title={title} action={right} filter={filter} level={as === "h3" ? 3 : 2} />
  );
}
