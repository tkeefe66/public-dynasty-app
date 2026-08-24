// SortDir is DEFINED IN Task 1's SortButton.tsx and imported here — do not
// declare a second copy. (Controller ruling, pre-flight scan.)
import type { SortDir } from "@/components/furniture/SortButton";

/**
 * Pure sorting for the draft board's two ledgers (`DraftBoard.tsx`'s
 * `PicksSection`/`OwnersSection`). Kept out of `DraftBoard.tsx` because the
 * ordering rules — decorated stable sort, nulls always last, ordinal
 * (non-alphabetical) columns — deserve their own unit tests independent of
 * any rendering, and `DraftBoard.tsx` is already large.
 */
export interface SortState {
  key: string;
  dir: "ascending" | "descending";
}

/**
 * Pure. Returns a NEW array; never mutates `rows`.
 *
 * Decorated stable sort: map to `{row, i}`, compare, fall back to the
 * original index `i` on a tie. `Array.prototype.sort` is spec-stable in
 * modern V8, but the explicit fallback makes the intent testable rather than
 * relying on engine behavior.
 *
 * Nulls sort last in BOTH directions — an absent figure is not a small one.
 * A null that sorted to the top on `descending` would read as the best pick
 * in the class, which is worse than the truth ("this pick has no reading on
 * this column yet").
 */
export function sortRows<T>(
  rows: T[],
  state: SortState | null,
  get: (row: T, key: string) => string | number | null | undefined,
): T[] {
  if (!state) return [...rows];
  const { key, dir } = state;

  const decorated = rows.map((row, i) => ({ row, i, v: get(row, key) }));

  decorated.sort((a, b) => {
    const aNull = a.v == null;
    const bNull = b.v == null;
    // Nulls last regardless of direction — never flipped by `dir` below.
    if (aNull && bNull) return a.i - b.i;
    if (aNull) return 1;
    if (bNull) return -1;

    let cmp: number;
    if (typeof a.v === "number" && typeof b.v === "number") {
      cmp = a.v - b.v;
    } else {
      cmp = String(a.v).localeCompare(String(b.v), undefined, { sensitivity: "base" });
    }
    if (cmp === 0) return a.i - b.i; // stable tie — original order, not direction-flipped
    return dir === "ascending" ? cmp : -cmp;
  });

  return decorated.map((d) => d.row);
}

/**
 * The next state for a click on `key`. First click on a numeric column opens
 * descending (the interesting end — the highest total, the biggest delta);
 * on a text column, ascending (A first). Clicking the already-active column
 * flips its direction rather than reopening at the default. Switching to a
 * different column opens that column fresh at its own default, ignoring
 * whatever direction the previous column was left in.
 */
export function nextSort(current: SortState | null, key: string, numeric: boolean): SortState {
  if (current && current.key === key) {
    return { key, dir: current.dir === "ascending" ? "descending" : "ascending" };
  }
  return { key, dir: numeric ? "descending" : "ascending" };
}

/** `aria-sort`/`SortButton`'s `sort` prop for one column, given the current
 *  state — `"none"` unless this column is the active one. Small helper so
 *  `DraftBoard.tsx` doesn't repeat the same ternary at every header cell. */
export function sortDirFor(state: SortState | null, key: string): SortDir {
  if (!state || state.key !== key) return "none";
  return state.dir;
}
