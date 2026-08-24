"""Offseason-safe construction of dynasty outlooks for the API refresh.

The CLI builds position rankings from Monte-Carlo projections; those don't
exist in the offseason. Here we substitute KTC value: position rankings ranked
by KTC desc. That is the only input ``build_dynasty_outlook`` needs that is not
already on the roster — the competitive-window model that used to need four
more is retired (see engine/gm_rating.py::rating_to_stage). Pure and
unit-tested.
"""

from __future__ import annotations

from datetime import date

from sleeper_dynasty.engine.dynasty import DynastyOutlook, build_dynasty_outlook
from sleeper_dynasty.models.league import DraftPick, Roster
from sleeper_dynasty.models.player import Player


def ktc_position_rankings(
    rosters: list[Roster],
    positions: dict[str, str],
    ktc_value_by_player: dict[str, float],
) -> dict[str, list[str]]:
    """position -> player_ids across the league, ranked by KTC value (best first).

    Offseason-safe substitute for projection-based rankings.
    """
    by_pos: dict[str, list[str]] = {}
    for r in rosters:
        for pid in (r.players or []):
            pos = positions.get(pid)
            if not pos:
                continue
            by_pos.setdefault(pos, []).append(pid)
    for pids in by_pos.values():
        pids.sort(key=lambda p: ktc_value_by_player.get(p, 0.0), reverse=True)
    return by_pos


def league_avg_age_by_position(
    rosters: list[Roster],
    players: dict[str, Player],
    as_of: date | None = None,
) -> dict[str, float]:
    """position -> mean age across EVERY rostered player in the league.

    Pooled over players, not averaged over owners' means. That is deliberate:
    an owner's own `AgeProfile.avg_age_by_position` is itself a pooled mean
    over that owner's players, so computing the league figure the same way
    keeps ONE definition of "mean age at a position". A mean-of-owner-means
    would introduce a second averaging step the owner-side figure does not
    have, and a figure that is computed two ways is exactly what this redesign
    exists to delete.

    K and DEF are skipped, matching `dynasty._SKIP_POSITIONS`, so the keys here
    are comparable to an `AgeProfile`'s. A position nobody in the league
    rosters yields no key — the rooms chart plots the OWNER's keys intersected
    with these, so an absent key is simply not drawn.
    """
    from sleeper_dynasty.engine.dynasty import _SKIP_POSITIONS

    ref = as_of or date.today()
    ages: dict[str, list[int]] = {}
    for r in rosters:
        for pid in (r.players or []):
            p = players.get(pid)
            if p is None or p.position in _SKIP_POSITIONS:
                continue
            age = p.age(as_of=ref)
            if age is None:
                continue
            ages.setdefault(p.position, []).append(age)
    return {pos: sum(v) / len(v) for pos, v in ages.items() if v}


def roster_value_ranks(
    roster_value_by_owner: dict[str, float],
) -> dict[str, dict[str, int]]:
    """uid -> {'rank': 1-based, 'of': N} by roster value desc (current owners)."""
    ordered = sorted(
        roster_value_by_owner,
        key=lambda u: roster_value_by_owner[u], reverse=True)
    n = len(ordered)
    return {uid: {"rank": i + 1, "of": n} for i, uid in enumerate(ordered)}


def build_outlooks_by_owner(
    *,
    rosters: list[Roster],
    players: dict[str, Player],
    traded_picks: list[DraftPick],
    positions: dict[str, str],
    ktc_value_by_player: dict[str, float],
    roster_to_user: dict[int, str],
    total_rosters: int,
    num_rounds: int = 4,
) -> tuple[dict[str, DynastyOutlook], dict[str, float]]:
    """Build a DynastyOutlook per current owner uid, plus the league's own
    per-position mean ages (offseason-safe).

    The league map is returned ALONGSIDE rather than set on each AgeProfile:
    it is league-wide data, and hanging it off a per-roster dataclass would
    duplicate it once per owner and invite the two copies to drift.

    position_rankings come from KTC value; nothing else is substituted.
    """
    rankings = ktc_position_rankings(rosters, positions, ktc_value_by_player)

    out: dict[str, DynastyOutlook] = {}
    for r in rosters:
        uid = roster_to_user.get(r.roster_id)
        if not uid:
            continue
        roster_players = [
            players[pid] for pid in (r.players or []) if pid in players]
        out[uid] = build_dynasty_outlook(
            roster=r,
            roster_players=roster_players,
            traded_picks=traded_picks,
            position_rankings=rankings,
            total_rosters=total_rosters,
            num_rounds=num_rounds,
        )
    return out, league_avg_age_by_position(rosters, players)


def _player_lite(p: Player, as_of: date) -> dict:
    return {
        "player_id": p.player_id,
        "full_name": p.full_name,
        "position": p.position,
        "age": p.age(as_of=as_of),
    }


def outlook_to_dict(
    outlook: DynastyOutlook,
    as_of: date | None = None,
    league_avg_age_by_position: dict[str, float] | None = None,
) -> dict:
    """JSON-safe serialization (Players -> lite dicts; tuple keys -> strings).

    `league_avg_age_by_position` defaults to `{}` rather than being omitted:
    the CLI path never computes it, and `owner_view` reads the key directly.
    An empty dict is a real reading ("no league comparison available"); a
    missing key would KeyError.
    """
    ref = as_of or date.today()
    ap = outlook.age_profile
    dc = outlook.draft_capital
    return {
        "age_profile": {
            "avg_age_by_position": ap.avg_age_by_position,
            "league_avg_age_by_position": league_avg_age_by_position or {},
            "overall_avg_age": ap.overall_avg_age,
            "aging_risks": [_player_lite(p, ref) for p in ap.aging_risks],
            "core_young": [_player_lite(p, ref) for p in ap.core_young],
        },
        "draft_capital": {
            "picks_by_season": {
                str(k): v for k, v in dc.picks_by_season.items()},
            "picks_by_season_round": {
                f"{s}-{rd}": v for (s, rd), v in dc.picks_by_season_round.items()},
            "net_vs_average": dc.net_vs_average,
            "status": dc.status,
        },
        "draft_needs": [
            {
                "position": n.position, "urgency": n.urgency, "reason": n.reason,
                "held": n.held, "ideal": n.ideal, "kind": n.kind,
            }
            for n in outlook.draft_needs
        ],
    }
