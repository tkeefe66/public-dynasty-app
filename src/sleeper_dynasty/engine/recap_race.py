"""Computed standings consequences for the Analyst; prose never does the math."""
from itertools import combinations


def _wins(row):
    return row.wins + row.ties / 2


def _table(rosters):
    ordered = sorted(rosters, key=lambda r: (_wins(r), r.points_for), reverse=True)
    keys = [(_wins(r), round(r.points_for, 2)) for r in ordered]
    return ordered, {r.roster_id: (keys.index(keys[i]) + 1, keys.count(keys[i]) > 1)
                     for i, r in enumerate(ordered)}


def build_race_context(before, after, league, week, *, verified=True, upcoming=None):
    settings = league.standings_settings
    if not verified or any(settings.get(k, 0) for k in ("divisions", "league_average_match", "playoff_seed_type")):
        return {"available": False, "reason": "League standings rules or reconstructed records are not verified; omit rank and playoff claims."}
    total_weeks = max(1, league.playoff_week_start - 1)
    remaining = max(0, total_weeks - week)
    emphasis = "playoff_race" if remaining <= 4 else "developing_race" if week > total_weeks / 3 else "early_trends"
    ordered, ranks = _table(after)
    _, old_ranks = _table(before)
    old = {r.roster_id: r for r in before}
    slots = league.num_playoff_teams
    cutoff = ordered[slots - 1] if 0 < slots < len(ordered) else None
    teams = []
    for r in ordered:
        prev = old[r.roster_id]
        can_catch = sum(_wins(o) + remaining >= _wins(r) for o in ordered if o.roster_id != r.roster_id)
        unreachable = sum(_wins(o) > _wins(r) + remaining for o in ordered if o.roster_id != r.roster_id)
        status = "in_race"
        if cutoff is not None:
            if can_catch < slots:
                status = "clinched_by_record"
            elif unreachable >= slots:
                status = "eliminated_by_record"
        teams.append({
            "owner": r.owner_name, "roster_id": r.roster_id,
            "record_before": [prev.wins, prev.losses, prev.ties],
            "record_after": [r.wins, r.losses, r.ties],
            "rank_before": old_ranks[r.roster_id][0] if week > 1 else None,
            "rank_after": ranks[r.roster_id][0], "rank_tied": ranks[r.roster_id][1],
            "points_for": round(r.points_for, 2),
            "points_for_before": round(prev.points_for, 2),
            "win_equivalent_gap_to_cutoff": round(_wins(cutoff) - _wins(r), 2) if cutoff else None,
            "playoff_status": status,
        })
    changed = []
    for a, b in combinations(ordered, 2):
        prior = _wins(old[a.roster_id]) - _wins(old[b.roster_id])
        now = _wins(a) - _wins(b)
        if week > 1 and prior != now and (prior <= 0 <= now or now <= 0 <= prior):
            changed.append({"side_a": a.owner_name, "side_b": b.owner_name,
                            "gap_before": prior, "gap_after": now,
                            "meaning": "Signed win-equivalent lead of side_a over side_b; points-for decides ranking when records tie."})
    by_id = {r.roster_id: r for r in after}
    matchups = {}
    for result in upcoming or []:
        if result.matchup_id is not None and result.roster_id in by_id:
            matchups.setdefault(result.matchup_id, []).append(by_id[result.roster_id])
    next_games = []
    for pair in matchups.values():
        if len(pair) != 2 or pair[0].roster_id == pair[1].roster_id:
            continue
        a, b = pair
        gap = _wins(a) - _wins(b)
        next_games.append({"side_a": a.owner_name, "side_b": b.owner_name,
                           "current_gap": gap, "gap_if_side_a_wins": gap + 1,
                           "gap_if_side_b_wins": gap - 1,
                           "basis": "Win-equivalent lead of side_a over side_b; not a predicted result or seed."})
    return {"available": True, "week": week, "weeks_remaining": remaining,
            "playoff_spots": slots, "emphasis": emphasis,
            "ranking_basis": "Overall wins plus half of ties, then total points for. Exact ties share rank. Not bracket seeding.",
            "teams": teams, "changed_gaps": changed, "upcoming_matchups": next_games,
            "claim_limits": "No odds, guaranteed seeds, must-win claims, or clinching/elimination beyond explicit playoff_status. Future outcomes remain conditional."}
