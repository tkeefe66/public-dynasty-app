import type { ReactNode } from "react";

/**
 * A franchise or player name — the primary identity of a row or card.
 *
 * WHY THIS EXISTS (it was missing, and its absence was a real bug): `Row` sets
 * the whole row to `--dim`, because most cells in a ledger are metadata. A NAME
 * is not metadata — it is the thing the reader is scanning for — so it takes
 * `--ink`. Without this component every converted ledger rendered its names in
 * dim, one step quieter than the figures beside them, which inverts the
 * hierarchy the ledger exists to express. Three separate conversions reproduced
 * that mistake by copying a call site that had it.
 *
 * The display face belongs to this CLASS, not to the row: scoping the font at
 * row level silently rendered card names in the sans face, so the same
 * franchise was Bricolage on desktop and Geist on a phone — two designs rather
 * than two densities.
 *
 * A name in a row truncates, because a fixed column cannot reflow. A name in a
 * card wraps and sets one step larger, because there it is the entry's whole
 * heading.
 */
export function Name({
  children,
  on = "row",
  className = "",
  title,
}: {
  children: ReactNode;
  /** "row" truncates at the column edge; "card" wraps and sets larger. */
  on?: "row" | "card";
  className?: string;
  title?: string;
}) {
  const card = on === "card";
  return (
    <span
      title={title}
      className={[
        "font-display tracking-[var(--track-name)] text-ink",
        card ? "font-extrabold text-section" : "font-bold text-name truncate",
        className,
      ].join(" ")}
    >
      {children}
    </span>
  );
}
