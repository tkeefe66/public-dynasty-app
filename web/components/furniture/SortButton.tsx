import type { ReactNode } from "react";
import { Mark } from "./Mark";
import { mergeClasses } from "./merge";

/**
 * Sort direction state. NOT carried on this component's `aria-sort` — see the
 * note on `SortButton` below for why `aria-sort` must live on the wrapping
 * `role="columnheader"` cell instead, never on this button. This union is
 * what the mark reads (`sort-asc` vs `sort-desc`) and what a caller passes to
 * both `SortButton` and its wrapping header cell's own `aria-sort`. Defined
 * exactly once, here: `SortButton` is the sole owner of this union, and a
 * later screen imports it rather than redeclaring a second one that could
 * drift.
 */
export type SortDir = "none" | "ascending" | "descending";

interface SortButtonProps {
  children?: ReactNode;
  sort?: SortDir;
  onClick?: () => void;
  align?: "left" | "right";
  className?: string;
  /** Accessible name for the column, used to build the button's `aria-label`
   *  ("Sort by {label}, currently {direction}"). Falls back to `children`
   *  when it's a plain string, which every current call site passes — pass
   *  this explicitly only when `children` isn't plain text. */
  label?: string;
}

/**
 * A sortable column header — mirrors `.design/components/controls/SortButton.jsx`.
 * Put it inside a `Row variant="head"` cell (see the `.prompt.md`).
 *
 * The 44px tap target lives on the BUTTON, not the row (`min-h-tap`), so a
 * header stays operable at any density; direction is carried visually by the
 * mark (`sort-asc` when ascending, `sort-desc` otherwise — including the
 * `"none"` default).
 *
 * THE INACTIVE MARK IS INVISIBLE, NOT DIM, and revealed on hover or keyboard
 * focus. It was `opacity-30` on every column, which meant a ten-column ledger
 * drew ten arrows of which nine said nothing — measured on the draft board,
 * that plus the definition triggers put 33px of chrome into tracks cut for
 * plain text and re-jumbled the very header a naming tier had just been added
 * to un-jumble. An arrow on the sorted column is information; an arrow on
 * every other column is decoration that costs width.
 *
 * It is `opacity-0`, NOT `hidden`/`w-0` — **the mark's box is always
 * reserved**. Collapsing it would make the label jump sideways by 12px on
 * hover, and the whole point is a calm header. A track must therefore still
 * be cut to fit label + mark + any definition trigger; hiding the mark buys
 * quiet, not room.
 *
 * ACCEPTED GAP: no touch affordance until tapped. The reveal is driven by
 * `:hover`/`:focus-visible` alone — at the draft board's ≥910px desktop gate
 * a touch device with a screen that size (iPad landscape is 1024px) gets
 * neither: no hover event exists, and a tap doesn't set `:focus-visible` the
 * way a keyboard `Tab` does. That means a sortable header shows no visual
 * cue that it's sortable until the reader taps it and sees the result. This
 * is accepted, not fixed — the identical trade the inactive-mark opacity
 * behavior above makes for keyboard/mouse users, just uncovered by a third
 * input mode this table's breakpoint happens to admit.
 *
 * `aria-sort` is NOT on this button. It is only valid on
 * `columnheader`/`rowheader`/`gridcell` — on `role="button"` it is dropped by
 * the accessibility layer, which is exactly how a table built from this
 * button shipped with no sort state announced to a screen reader at all. The
 * WRAPPING `role="columnheader"` cell owns it instead (`sortDirFor(sort,
 * key)` passed to both the cell and this button), matching
 * `StandingsTable.tsx`'s own header cell — do not re-add `aria-sort` here;
 * that would just be inert on `role="button"` and invites the same bug back
 * if a future caller assumes THIS is where sort state lives. What this
 * button DOES own is the descriptive name a screen reader announces for the
 * control itself: `aria-label="Sort by {label}, currently {direction}"` (the
 * direction clause omitted while unsorted), the same pattern
 * `StandingsTable.tsx` uses — without it the accessible name is just the
 * visible text ("#", "GS"), which doesn't say the control sorts anything.
 *
 * Font, letter-spacing and colour otherwise inherit from the head Row, so a
 * sortable column stays typographically identical to a fixed one — EXCEPT
 * `text-transform`, which Tailwind's preflight resets to `none` on `<button>`
 * specifically. That is why `uppercase` is repeated here rather than left to
 * inherit: dropping it is what split the standings header in two before it
 * was caught (see `Row.tsx`'s and `StandingsTable.tsx`'s own note on the same
 * bug). `text-ink` is likewise only applied when the column is active —
 * inactive stays `inherit` (the row's `text-dim`), same as the design source.
 */
export function SortButton({
  children,
  sort = "none",
  onClick,
  align = "left",
  className = "",
  label,
}: SortButtonProps) {
  const active = sort !== "none";
  const base = `group/sort inline-flex min-h-tap items-center gap-[5px] border-0 bg-transparent p-0 uppercase cursor-pointer ${
    align === "right" ? "w-full justify-end" : "justify-start"
  } ${active ? "text-ink" : ""}`;

  const accessibleLabel = label ?? (typeof children === "string" ? children : undefined);
  const ariaLabel = accessibleLabel
    ? `Sort by ${accessibleLabel}${active ? `, currently ${sort}` : ""}`
    : undefined;

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={onClick}
      className={mergeClasses(base, className)}
    >
      {children}
      <Mark
        name={sort === "ascending" ? "sort-asc" : "sort-desc"}
        size={12}
        /* opacity only — the box stays reserved at every state, so nothing
         * shifts when the mark appears. See the note above. */
        className={
          active
            ? undefined
            : "opacity-0 transition-opacity group-hover/sort:opacity-60 group-focus-visible/sort:opacity-60"
        }
      />
    </button>
  );
}
