"""Pure regular-season standings reconstruction from assembled matchups.

W/L/T is read directly from each roster-week's ``team_points`` vs
``opponent_points`` (the matchups dict is already opponent-paired by
``grader_io._assemble_played_matchups``), so no matchup_id re-pairing is needed.

Standings count REGULAR-SEASON weeks only (``week < playoff_week_start``) to match
Sleeper's authoritative ``Roster`` record, which excludes playoff bracket games.
"""

from __future__ import annotations

from dataclasses import dataclass

from sleeper_dynasty.models.league import Roster


@dataclass
class StandingRow:
    owner_id: str
    roster_id: int
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    rank: int = 0


def standings_as_of(
    matchups: dict[tuple[str, int, int], dict],
    *,
    league_id: str,
    through_week: int,
    playoff_week_start: int,
    roster_to_user: dict[int, str],
) -> list[StandingRow]:
    """Regular-season standings for one league through ``through_week`` inclusive.

    Counts only weeks ``1 <= week <= through_week`` and ``week < playoff_week_start``.
    Roster-weeks with missing points (unplayed) are skipped. Ranks by
    (wins desc, points_for desc) — Sleeper's default tiebreak.
    """
    acc: dict[int, StandingRow] = {}
    for (lg, wk, rid), entry in matchups.items():
        if lg != league_id or wk > through_week or wk >= playoff_week_start:
            continue
        tp = entry.get("team_points")
        op = entry.get("opponent_points")
        if tp is None or op is None:
            continue
        row = acc.get(rid)
        if row is None:
            row = StandingRow(
                owner_id=roster_to_user.get(rid, str(rid)),
                roster_id=rid, wins=0, losses=0, ties=0,
                points_for=0.0, points_against=0.0,
            )
            acc[rid] = row
        tp, op = float(tp), float(op)
        row.points_for += tp
        row.points_against += op
        if tp > op:
            row.wins += 1
        elif tp < op:
            row.losses += 1
        else:
            row.ties += 1
    rows = sorted(acc.values(), key=lambda r: (-r.wins, -r.points_for))
    for i, r in enumerate(rows, start=1):
        r.rank = i
    return rows


def standings_history(
    matchups: dict[tuple[str, int, int], dict],
    *,
    league_id: str,
    season: int,
    playoff_week_start: int,
    roster_to_user: dict[int, str],
) -> dict[str, list[StandingRow]]:
    """Standings after each completed regular-season week of one league-season.

    Returns ``{"{season}-{week:02d}": [StandingRow, ...]}`` for every regular-season
    week present in ``matchups`` for ``league_id``.
    """
    weeks = sorted({
        wk for (lg, wk, _rid) in matchups
        if lg == league_id and wk < playoff_week_start
    })
    out: dict[str, list[StandingRow]] = {}
    for wk in weeks:
        out[f"{season:04d}-{wk:02d}"] = standings_as_of(
            matchups, league_id=league_id, through_week=wk,
            playoff_week_start=playoff_week_start, roster_to_user=roster_to_user,
        )
    return out


def validate_against_roster(
    reconstructed: list[StandingRow], rosters: list[Roster]
) -> list[str]:
    """Compare a fully-reconstructed regular-season table against Sleeper's
    authoritative ``Roster`` records. Returns human-readable deltas ([] when exact).

    Sleeper's roster wins/losses already account for median/division rules, so a
    mismatch flags a league whose standings need extra handling. Points-for is
    compared with a small tolerance (rounding). Ties are not compared (they almost
    never occur in Sleeper leagues).
    """
    by_rid = {r.roster_id: r for r in reconstructed}
    deltas: list[str] = []
    for roster in rosters:
        got = by_rid.get(roster.roster_id)
        if got is None:
            deltas.append(f"roster {roster.roster_id}: no reconstructed row")
            continue
        if got.wins != roster.wins or got.losses != roster.losses:
            deltas.append(
                f"roster {roster.roster_id}: record {got.wins}-{got.losses} "
                f"!= sleeper {roster.wins}-{roster.losses}"
            )
        if abs(got.points_for - float(roster.points_for)) > 1.0:
            deltas.append(
                f"roster {roster.roster_id}: pf {got.points_for:.1f} "
                f"!= sleeper {float(roster.points_for):.1f}"
            )
    return deltas


def all_play_win_pct(
    matchups: dict[tuple[str, int, int], dict],
    *,
    league_id: str,
    playoff_week_start: int,
    roster_to_user: dict[int, str],
) -> dict[str, float]:
    """Share of all-play matchups won, over one league's regular season.

    For each week, every roster is scored against every *other* roster that
    played that week: a higher score is a win, an equal score is half. This is
    the schedule-luck-free reading of a season — it uses the same weekly
    ``team_points`` as ``standings_as_of`` and answers "how good were you"
    rather than "who did you happen to draw".

    The denominator is the rosters that actually played that week, NOT the
    league size. A bye, or a matchup pair dropped upstream for having no score,
    removes those rosters from that week entirely; dividing by league size
    would mark every remaining roster down for an absence.

    Rosters with no played weeks are omitted rather than returned at 0.0 — no
    games is an absence, not a shutout.
    """
    by_week: dict[int, dict[int, float]] = {}
    for (lg, week, roster_id), entry in matchups.items():
        if lg != league_id or week >= playoff_week_start or week < 1:
            continue
        pts = entry.get("team_points")
        if pts is None:
            continue
        by_week.setdefault(week, {})[roster_id] = float(pts)

    wins: dict[int, float] = {}
    played: dict[int, int] = {}
    for scores in by_week.values():
        roster_ids = list(scores)
        if len(roster_ids) < 2:
            continue
        for rid in roster_ids:
            mine = scores[rid]
            beat = sum(1 for other in roster_ids if other != rid and mine > scores[other])
            tied = sum(1 for other in roster_ids if other != rid and mine == scores[other])
            wins[rid] = wins.get(rid, 0.0) + beat + 0.5 * tied
            played[rid] = played.get(rid, 0) + len(roster_ids) - 1

    out: dict[str, float] = {}
    for rid, n in played.items():
        uid = roster_to_user.get(rid)
        if uid and n:
            out[uid] = wins[rid] / n
    return out
