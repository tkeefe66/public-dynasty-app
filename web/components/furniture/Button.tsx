import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { mergeClasses } from "./merge";

const BASE =
  "inline-flex items-center gap-2 min-h-tap rounded-sm bg-stamp text-stamp-ink hover:bg-stamp-lit active:bg-stamp-deep disabled:bg-rule disabled:text-dim disabled:cursor-not-allowed font-mono text-label font-bold uppercase tracking-[0.11em] transition-colors";

interface CommonProps {
  className?: string;
  children: ReactNode;
}

type ButtonAsButton = CommonProps & { as?: "button" } & Omit<
  ComponentPropsWithoutRef<"button">,
  "className" | "children"
>;

type ButtonAsAnchor = CommonProps & { as: "a" } & Omit<
  ComponentPropsWithoutRef<"a">,
  "className" | "children"
>;

type ButtonAsLink = CommonProps & { as: "link" } & Omit<
  ComponentPropsWithoutRef<typeof Link>,
  "className" | "children"
>;

export type ButtonProps = ButtonAsButton | ButtonAsAnchor | ButtonAsLink;

/**
 * Furniture — the shared primary-button dialect, replacing
 * `components/agate/Button.tsx` (`.design/components/controls/Button.jsx` +
 * `Button.prompt.md`: "the action control — a stamp-filled primary ... always
 * at least 44px tall").
 *
 * Stamp is still the ground (`tokens/stamp.css` § "the primary button fill",
 * one of Furniture's five sanctioned stamp places) with the same
 * hover/active step through `--stamp-lit`/`--stamp-deep`. What changes under
 * Furniture: a real radius (`rounded-sm`, `--radius-sm` — Agate was zero
 * radius everywhere), an unconditional 44px tap target (`min-h-tap`), the
 * type-scale label size instead of a hardcoded pixel value (`text-label`,
 * never `text-[10px]` — Tailwind preflight sets `text-transform: none` on
 * `button`, so `uppercase` has to live on the button itself, not be
 * inherited), and a real disabled colour (`disabled:bg-rule
 * disabled:text-dim`) rather than an opacity dip.
 *
 * The design system's `Button.jsx` also draws an outlined `ghost` variant and
 * `icon`/`iconAfter` slots. This component does not: the Agate original never
 * had a `variant`, `icon`, or `iconAfter` prop — it is the single sanctioned
 * PRIMARY fill, and the system's own guidance is "one primary per view; for
 * an outline or a bigger-view link, reach for `MonoLink`, never a second
 * button." Introducing a ghost mode here would be inventing an API the 14
 * existing call sites were never built against.
 *
 * `as` picks the rendered element: "button" (default — needs `onClick`),
 * "link" (`next/link`, client-side nav), or "a" (a plain anchor, for call
 * sites that deliberately want a full re-navigation instead of client
 * routing — e.g. re-running a force-dynamic server fetch with no client JS).
 * Padding is NOT baked in (`px-4 py-2` vs `px-3 py-2` differ per call site)
 * — pass it via `className`.
 */
export function Button(props: ButtonProps) {
  const { className = "", children, as = "button", ...rest } = props;
  /* mergeClasses, not concatenation. Two Tailwind utilities of the same family
   * have equal specificity, so a caller override wins or loses by stylesheet
   * order rather than intent. Today every caller that overlaps a family happens
   * to pass the identical value already in BASE, so nothing is visibly broken —
   * which is exactly how this stays broken until someone passes a DIFFERENT
   * `disabled:bg-*` and it silently does nothing. Caught in review. */
  const cls = mergeClasses(BASE, className ?? "");

  if (as === "a") {
    const anchorRest = rest as Omit<ComponentPropsWithoutRef<"a">, "className" | "children">;
    return (
      <a className={cls} {...anchorRest}>
        {children}
      </a>
    );
  }

  if (as === "link") {
    const linkRest = rest as Omit<ComponentPropsWithoutRef<typeof Link>, "className" | "children">;
    return (
      <Link className={cls} {...linkRest}>
        {children}
      </Link>
    );
  }

  const buttonRest = rest as Omit<ComponentPropsWithoutRef<"button">, "className" | "children">;
  return (
    <button type="button" className={cls} {...buttonRest}>
      {children}
    </button>
  );
}
