/**
 * Start % — the share of a haul's Total Points that were actually STARTED.
 *
 * One rule, three call sites (`DraftBoard.tsx`, `DraftPicksMobile.tsx`,
 * `ownerdeepdive/PastPicksTable.tsx`), mirroring the backend's own
 * single-definition contract for the same ratio
 * (`api/app/services/start_rate.py`): "one definition, two call sites... so
 * the number cannot mean two things depending on which screen you are
 * looking at." Phase 2 grew three independent TS re-implementations that
 * agreed with each other but not with the Python — every one of them gated
 * on `!total`, which is true only for a total of exactly 0. The Python gates
 * on `total > 0`. A K or DEF can score negative in a week it started (a
 * missed extra point, a safety allowed), so a pick's `production_total` can
 * be negative — reachable, not hypothetical. `!total` lets a negative total
 * fall through and renders a percentage computed from a negative
 * denominator; `start_rate.py` returns `None` for exactly that case, because
 * a ratio over a negative denominator is meaningless, not merely unknown.
 *
 * NULL, NEVER "0%" OR A NEGATIVE-DENOMINATOR PERCENTAGE, when there is
 * nothing sound to divide. Callers keep their own em-dash presentation —
 * this module owns the rule, not the markup.
 */

/** Formatted whole-percentage string ("62%"), or `null` when `total` is not
 *  strictly positive — mirrors `start_rate.py`'s `total > 0` gate exactly. */
export function startPct(started: number | null | undefined, total: number | null | undefined): string | null {
  if (total == null || total <= 0) return null;
  return `${Math.round((100 * (started ?? 0)) / total)}%`;
}
