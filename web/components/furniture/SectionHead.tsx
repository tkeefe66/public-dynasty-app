import type { ReactNode } from "react";

/**
 * A section heading, and the one place the type change is most visible.
 *
 * Agate set these as Archivo 900 UPPERCASE bare nouns — `FRANCHISES`,
 * `SCOREBOARD`. Furniture sets them in Bricolage 700 **mixed case**: the change
 * of case matters as much as the change of face, because the uppercase Archivo
 * is precisely what read as shouting at consumer scale. Do not reintroduce
 * `uppercase` here — mono labels keep their caps, headings do not.
 *
 * `meta` is the section's scope line ("Career-wide · 12 rows"), which stays
 * mono and dim: it is metadata about the ledger, not part of the heading.
 *
 * THREE SLOTS, AND THE SIDE IS THE MEANING. `filter` sits immediately beside
 * the title; `meta` and `action` sit at the far end. A filter changes what the
 * heading names, so it reads as part of the heading — pushed to the opposite
 * margin it becomes a thing you have to find, and at a wide viewport it can end
 * up a foot away from the words it modifies. `meta` (a count, a scope line) and
 * `action` (a back link, an out-link, a button) are *about* the section rather
 * than controls over it, and they keep the right.
 */
export function SectionHead({
  title,
  id,
  meta,
  action,
  filter,
  level = 2,
}: {
  title: string;
  id?: string;
  meta?: ReactNode;
  action?: ReactNode;
  /** A single-select control governing this section — put it here, not in
   *  `action`, so it lands next to the heading it filters. */
  filter?: ReactNode;
  /** 2 for a page section, 3 for an entry inside a prose list. */
  level?: 2 | 3;
}) {
  const H = (level === 3 ? "h3" : "h2") as "h2" | "h3";
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-rule pb-2">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1.5">
        <H
          id={id}
          className={`font-display font-bold tracking-[-0.024em] ${
            level === 3 ? "text-name" : "text-section"
          }`}
        >
          {title}
        </H>
        {filter}
      </div>
      {meta && (
        <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
          {meta}
        </span>
      )}
      {action}
    </div>
  );
}
