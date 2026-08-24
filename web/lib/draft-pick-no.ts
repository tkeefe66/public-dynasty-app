/**
 * A pick's position within its own round — the second half of the
 * `round.position` code every draft-board surface renders (`1.01`, `2.03`).
 *
 * NOT `slot` (the team's draft position/seed): in a snake draft, order
 * reverses every even round, so `slot` only equals within-round position in
 * odd rounds. Rendering `slot` directly mislabels every even-round pick
 * (round 2's first pick, universally "2.01", showed as "2.12" for a slot-12
 * team) and, because rows sort by `pick_no`, makes the round's labels count
 * downward instead of ascending.
 *
 *     within = pick_no - (round - 1) * picks_in_round
 *
 * Falls back to `slot` when `picks_in_round` is missing, zero, or the
 * derivation comes out non-positive (bad/partial data) — guards the division
 * and avoids ever rendering zero or a negative position. The fallback is
 * harmless on a linear (non-snake) draft, where `slot` and within-round
 * position already coincide.
 */
export function pickPositionInRound(
  pickNo: number,
  round: number,
  slot: number,
  picksInRound?: number | null,
): number {
  if (!picksInRound) return slot;
  const within = pickNo - (round - 1) * picksInRound;
  return within > 0 ? within : slot;
}
