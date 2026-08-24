import { LatestTrade } from "./types";

/* ---------------------------------------------------------------------------
 * The dashboard lead's verdict, as pure functions so the copy rules are
 * testable without rendering. Both readings are deterministic — no LLM, and
 * no claim the payload can't support.
 * ------------------------------------------------------------------------ */

/** Has anybody actually scored? A 0-0 production pair is the offseason and
 *  pre-week-1 default, and the POINTS cell prints it as unscored. The headline
 *  reads from the same fact, so the two can never contradict each other —
 *  belt-and-braces over the backend's own tie rule
 *  (`aggregations.py::_strict_winner`), which already leaves
 *  `production_winner` null on a tie. */
function fieldIsScored(t: LatestTrade): boolean {
  const split = t.production_split;
  return !(split && split[0] === 0 && split[1] === 0);
}

/** Three winner forms plus a fallback:
 *
 *  - both lenses, one owner → "won this one on both counts"
 *  - both lenses, two owners → the tension worth telling
 *  - value settled, field not → says so rather than implying a sweep
 *  - no value winner (pre-verdict payload, too few graded sides, or a
 *    0.0-0.0 wash on the swing) → the pre-verdict headline, kept verbatim. */
export function tradeHeadline(t: LatestTrade): string {
  const value = t.value_winner;
  const production = fieldIsScored(t) ? t.production_winner : null;
  if (value && production) {
    return value.user_id === production.user_id
      ? `${value.owner_name} won this one on both counts.`
      : `${value.owner_name} won the value. ${production.owner_name} won the field.`;
  }
  if (value) {
    return `${value.owner_name} won the value. Nobody's scored yet.`;
  }
  const names = t.parties.map((p) => p.owner_name).join(" & ");
  return `${names}'s trade is still the loudest swing on the board.`;
}

export type PointsReading =
  | { kind: "unscored" }
  | { kind: "split"; left: string; right: string; winner: "left" | "right" | null };

/** The POINTS cell. Received-only totals read head-to-head ("179.8 vs 58.3"),
 *  never as a swing — Trade Value is the only swing metric. A lens both sides
 *  left at zero is unscored, matching the trade page
 *  (trade_view.py::_realized_lens_totals): an offseason trade whose players
 *  haven't taken a snap must not read as a 0.0-vs-0.0 result.
 *
 *  Three or more sides (production_split null) is also unscored. There is no
 *  head-to-head to draw, and the only production figure the payload carries —
 *  swing_prod — is a spread across every side, not any one owner's total;
 *  printing it under a POINTS label would misdescribe it. */
export function pointsReading(t: LatestTrade): PointsReading {
  const split = t.production_split;
  if (!split) return { kind: "unscored" };
  const [left, right] = split;
  if (left === 0 && right === 0) return { kind: "unscored" };
  // Compare what the reader sees, not the raw floats: 58.31 and 58.34 both
  // print "58.3", and emphasizing one of two identical figures reads as a
  // rendering bug. A tie after rounding emphasizes neither side.
  const leftText = left.toFixed(1);
  const rightText = right.toFixed(1);
  return {
    kind: "split",
    left: leftText,
    right: rightText,
    winner: leftText === rightText ? null : right > left ? "right" : "left",
  };
}
