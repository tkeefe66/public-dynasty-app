"""Pure draft-based Outlook signals: future pick value (capital) and past pick
quality vs slot tier (skill). No I/O — callers pass clean inputs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sleeper_dynasty.models.league import DraftPick


def pick_holdings_value(
    *,
    traded_picks: list[DraftPick],
    roster_ids: list[int],
    seasons: list[int],
    num_rounds: int,
    pick_values: dict[tuple[int, int], float],
    tier_by_roster: dict[int, str] | None = None,
    tiered_values: dict[tuple[int, int, str], float] | None = None,
) -> dict[int, float]:
    """KTC value of the future picks each roster holds.

    Every roster starts owning its own ``(season, round)`` pick across the
    outlook ``seasons``; ``traded_picks`` reassign ownership. Value = sum of
    ``pick_values[(season, round)]`` over held picks (missing slot -> 0).
    """
    owner_of: dict[tuple[int, int, int], int] = {}
    for rid in roster_ids:
        for s in seasons:
            for rd in range(1, num_rounds + 1):
                owner_of[(s, rd, rid)] = rid
    for p in traded_picks:
        key = (p.season, p.round, p.original_owner_id)
        if key in owner_of:
            owner_of[key] = p.current_owner_id

    tier_by_roster = tier_by_roster or {}
    tiered_values = tiered_values or {}
    value: dict[int, float] = {rid: 0.0 for rid in roster_ids}
    for (s, rd, orig), owner in owner_of.items():
        tier = tier_by_roster.get(orig, "")
        value[owner] = value.get(owner, 0.0) + tiered_pick_value(
            s, rd, tier, tiered_values, pick_values)
    return value


def strength_tiers(value_by_owner: dict) -> dict:
    """Rank owners by value desc, split into thirds: strongest third -> 'late'
    (picks land late, worth less), middle -> 'mid', weakest -> 'early' (worth
    most). Fewer than 3 owners -> all 'mid' (no meaningful ranking)."""
    owners = sorted(value_by_owner, key=lambda o: value_by_owner[o], reverse=True)
    n = len(owners)
    if n < 3:
        return {o: "mid" for o in owners}
    labels = ("late", "mid", "early")
    return {o: labels[min(2, i * 3 // n)] for i, o in enumerate(owners)}


def tiered_pick_value(
    season: int, rnd: int, tier: str,
    tiered: dict[tuple[int, int, str], float],
    round_avg: dict[tuple[int, int], float],
) -> float:
    """Tiered value with round-average fallback, then 0."""
    v = tiered.get((season, rnd, tier))
    if v is not None:
        return float(v)
    return float(round_avg.get((season, rnd), 0.0))


@dataclass
class DraftedPick:
    draft_id: str
    round: int
    slot: int            # 1-based position within the round
    picks_in_round: int
    player_id: str
    drafter_id: str      # owner uid who made the selection
    draft_season: int = 0  # NFL season year of the draft (0 = unknown)
    pick_no: int = 0     # overall pick number, 1-based (round 2 slot 1 = 13)
    draft_kind: str = "rookie"  # "rookie" | "full"
    is_keeper: bool = False     # kept, not drafted — shown but never scored
    gradeable: bool = True      # False for auction — results only, no grade


# ``build_rookie_picks`` lived here: the origin-season heuristic for "which
# drafts count". ``draft_class.build_draft_classes`` + ``build_draft_picks``
# replaced it — selection keys on Sleeper's own ``settings.player_type`` and
# is format-aware — and it is deleted rather than kept around, since dead
# production code with passing tests reads as a supported second answer to a
# question that must have exactly one.


def _zscores(vals: list[float]) -> list[float]:
    n = len(vals)
    if n == 0:
        return []
    mean = sum(vals) / n
    sd = (sum((x - mean) ** 2 for x in vals) / n) ** 0.5
    return [0.0 if sd == 0 else (x - mean) / sd for x in vals]


def _tier(slot: int, picks_in_round: int) -> int:
    return min(2, (slot - 1) * 3 // max(1, picks_in_round))


def draft_skill(
    *,
    picks: list[DraftedPick],
    ktc_by_player: dict[str, float],
    production_by_player: dict[str, float],
    games_by_player: dict[str, int] | None = None,
    min_games: int = 17,
    shrink_k: float = 3.0,
    axis: str = "blend",
) -> dict[str, float]:
    """Per-owner drafting skill: each pick's outcome minus the average outcome
    of its (draft, round, tier) peers, averaged over the owner's picks with
    small-sample shrinkage. Owners with no graded picks are absent.

    ``axis`` selects what "outcome" means:

    - "blend" (dynasty rookie drafts): value and production, 50/50. When
      ``games_by_player`` is provided a pick is "played" iff the player logged
      ``>= min_games`` game-weeks with points > 0; unplayed picks are judged on
      value alone so rookies who have not had a full season are not penalised
      for missing points. Production z-scores are computed over played picks
      only.
    - "production" (redraft and keeper full drafts): production alone. There is
      no unplayed carve-out — a redraft pick that never played scored nothing,
      and that is the real answer rather than missing data. Value is ignored
      entirely, because these leagues have no price history behind it.

    **Keeper picks are excluded outright.** A keep is not a draft decision, and
    leaving one in the peer group would raise what its round is expected to
    return, penalising everyone who actually picked there. **Non-gradeable
    picks (auction) are excluded too** — an auction's ``pick_no`` is
    chronological, not positional, so it carries no meaningful slot to judge
    against a peer tier.
    """
    picks = [p for p in picks if not p.is_keeper and p.gradeable]
    if not picks:
        return {}

    if axis == "production":
        outcome = _zscores(
            [float(production_by_player.get(p.player_id, 0.0)) for p in picks])
    else:
        zk = _zscores([float(ktc_by_player.get(p.player_id, 0.0)) for p in picks])
        if games_by_player is None:
            zp = _zscores(
                [float(production_by_player.get(p.player_id, 0.0)) for p in picks])
            outcome = [0.5 * zk[i] + 0.5 * zp[i] for i in range(len(picks))]
        else:
            played = [
                int(games_by_player.get(p.player_id, 0)) >= min_games for p in picks
            ]
            played_indices = [i for i, is_played in enumerate(played) if is_played]
            played_prods = [
                float(production_by_player.get(picks[i].player_id, 0.0))
                for i in played_indices
            ]
            played_zp = _zscores(played_prods)
            zp_by_idx: dict[int, float] = {
                played_indices[k]: played_zp[k] for k in range(len(played_indices))
            }
            outcome = []
            for i in range(len(picks)):
                if played[i]:
                    outcome.append(0.5 * zk[i] + 0.5 * zp_by_idx[i])
                else:
                    outcome.append(zk[i])

    tier_groups: dict[tuple, list[int]] = defaultdict(list)
    round_groups: dict[tuple, list[int]] = defaultdict(list)
    for i, p in enumerate(picks):
        tier_groups[(p.draft_id, p.round, _tier(p.slot, p.picks_in_round))].append(i)
        round_groups[(p.draft_id, p.round)].append(i)

    tot: dict[str, float] = defaultdict(float)
    cnt: dict[str, int] = defaultdict(int)
    for i, p in enumerate(picks):
        g = tier_groups[(p.draft_id, p.round, _tier(p.slot, p.picks_in_round))]
        idxs = g if len(g) >= 2 else round_groups[(p.draft_id, p.round)]
        exp = sum(outcome[j] for j in idxs) / len(idxs)
        tot[p.drafter_id] += outcome[i] - exp
        cnt[p.drafter_id] += 1
    return {uid: tot[uid] / (cnt[uid] + shrink_k) for uid in tot}
