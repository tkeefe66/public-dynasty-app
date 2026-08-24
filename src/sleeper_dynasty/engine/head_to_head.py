"""Pure head-to-head record reconstruction from assembled matchups.

For one league's regular season, tally each owner's W/L/T and points for/against
against every league-mate they played. Reads the same opponent-paired matchups
dict the standings reconstruction uses (``cli._assemble_played_matchups``), which
now carries ``opponent_roster_id`` so each roster-week resolves its opponent's
owner directly — no matchup_id re-pairing needed.

Scoped to ONE league (one season), keyed by owner_id. The chain layer aggregates
per-season results into all-time records by owner_id (stable across seasons),
the same owner-keyed, season-scoped pattern as the standings snapshot store.

Regular-season weeks only (``week < playoff_week_start``), matching standings and
Sleeper's authoritative ``Roster`` record.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class H2HRecord:
    opponent_id: str
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0


def head_to_head_records(
    matchups: dict[tuple[str, int, int], dict],
    *,
    league_id: str,
    roster_to_user: dict[int, str],
    playoff_week_start: int,
) -> dict[str, dict[str, H2HRecord]]:
    """Per-owner head-to-head records for one league's regular season.

    Returns ``owner_id -> {opponent_owner_id: H2HRecord}``. Counts only weeks
    ``week < playoff_week_start`` for ``league_id``; roster-weeks with missing
    points (unplayed) or no resolvable opponent are skipped.
    """
    out: dict[str, dict[str, H2HRecord]] = {}
    for (lg, wk, rid), entry in matchups.items():
        if lg != league_id or wk >= playoff_week_start:
            continue
        tp = entry.get("team_points")
        op = entry.get("opponent_points")
        opp_rid = entry.get("opponent_roster_id")
        if tp is None or op is None or opp_rid is None:
            continue
        owner = roster_to_user.get(rid, str(rid))
        opp_owner = roster_to_user.get(opp_rid, str(opp_rid))
        rec = out.setdefault(owner, {}).get(opp_owner)
        if rec is None:
            rec = H2HRecord(opponent_id=opp_owner)
            out[owner][opp_owner] = rec
        tp, op = float(tp), float(op)
        rec.points_for += tp
        rec.points_against += op
        if tp > op:
            rec.wins += 1
        elif tp < op:
            rec.losses += 1
        else:
            rec.ties += 1
    return out


def aggregate_head_to_head(
    per_league: list[dict[str, dict[str, H2HRecord]]],
) -> dict[str, dict[str, H2HRecord]]:
    """Merge per-league head-to-head results into one chain-wide record set.

    Owner ids are stable across the chain's leagues, so records for the same
    (owner, opponent) pair sum across seasons. Returns a fresh structure; the
    inputs are not mutated.
    """
    out: dict[str, dict[str, H2HRecord]] = {}
    for league in per_league:
        for owner, opps in league.items():
            for opp, rec in opps.items():
                agg = out.setdefault(owner, {}).get(opp)
                if agg is None:
                    agg = H2HRecord(opponent_id=opp)
                    out[owner][opp] = agg
                agg.wins += rec.wins
                agg.losses += rec.losses
                agg.ties += rec.ties
                agg.points_for += rec.points_for
                agg.points_against += rec.points_against
    return out
