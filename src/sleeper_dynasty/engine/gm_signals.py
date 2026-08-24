"""Pure extractors that turn raw league data into GM-rating pillar signals.

- ``outcome_signals``: career season-results signals from final standings +
  playoff-bracket results.

Returns ``uid -> {signal: value}`` in the shape ``compute_gm_ratings`` expects
for a pillar; every requested owner gets an entry (zero defaults when absent).
"""

from __future__ import annotations

from sleeper_dynasty.engine.standings import StandingRow


def outcome_signals(
    *,
    standings_by_season: dict[int, list[StandingRow]],
    bracket_results_by_season: dict[int, dict[str, dict]],
    num_playoff_teams_by_season: dict[int, int],
    owners: list[str],
) -> dict[str, dict[str, float]]:
    """Career outcome signals per owner, aggregated across seasons.

    - championships: count of titles (``bracket_results[season][uid]["champion"]``).
    - playoff_depth: sum of playoff rounds won across seasons.
    - made_playoffs: rate (made / participated), final rank <= num_playoff_teams.
    - final_seed: average inverted final rank (``total_rosters + 1 - rank``; 1st = best).
    - points_for_rank: average inverted points-for rank within each season.
    """
    # Accumulators.
    champs: dict[str, float] = {u: 0.0 for u in owners}
    depth: dict[str, float] = {u: 0.0 for u in owners}
    made: dict[str, int] = {u: 0 for u in owners}
    seasons_played: dict[str, int] = {u: 0 for u in owners}
    seed_sum: dict[str, float] = {u: 0.0 for u in owners}
    pf_sum: dict[str, float] = {u: 0.0 for u in owners}

    for season, rows in standings_by_season.items():
        total = len(rows)
        if total == 0:
            continue
        playoff_teams = num_playoff_teams_by_season.get(season, 0)
        brackets = bracket_results_by_season.get(season, {})
        # Points-for rank within the season (1 = highest pf).
        pf_order = sorted(rows, key=lambda r: r.points_for, reverse=True)
        pf_rank = {r.owner_id: i + 1 for i, r in enumerate(pf_order)}
        for r in rows:
            u = r.owner_id
            if u not in champs:  # owner not in the requested set; skip
                continue
            seasons_played[u] += 1
            seed_sum[u] += (total + 1 - r.rank)
            pf_sum[u] += (total + 1 - pf_rank[u])
            if playoff_teams and r.rank <= playoff_teams:
                made[u] += 1
            br = brackets.get(u) or {}
            if br.get("champion"):
                champs[u] += 1
            depth[u] += float(br.get("rounds_won", 0) or 0)

    out: dict[str, dict[str, float]] = {}
    for u in owners:
        n = seasons_played[u]
        out[u] = {
            "championships": champs[u],
            "playoff_depth": depth[u],
            "made_playoffs": (made[u] / n) if n else 0.0,
            "final_seed": (seed_sum[u] / n) if n else 0.0,
            "points_for_rank": (pf_sum[u] / n) if n else 0.0,
        }
    return out


def bracket_results(
    winners_bracket: list[dict],
    roster_to_user: dict[int, str],
) -> dict[str, dict]:
    """Per owner: ``{champion: bool, runner_up: bool, rounds_won: int}`` from a
    Sleeper winners-bracket. ``rounds_won`` counts title-path wins; the
    championship game is the ``p == 1`` match (or the highest round)."""
    games = winners_bracket or []
    rounds_won: dict[int, int] = {}
    for g in games:
        if g.get("p") not in (None, 1):
            continue  # skip consolation/placement games (3rd place, etc.)
        w = g.get("w")
        if w is not None:
            rounds_won[w] = rounds_won.get(w, 0) + 1

    final = None
    p1 = [g for g in games if g.get("p") == 1]
    if p1:
        final = p1[0]
    elif games:
        maxr = max((g.get("r") or 0) for g in games)
        finals = [g for g in games if (g.get("r") or 0) == maxr]
        final = finals[0] if finals else None
    champ_rid = final.get("w") if final else None
    runner_rid = final.get("l") if final else None

    out: dict[str, dict] = {}
    for rid, n in rounds_won.items():
        uid = roster_to_user.get(rid)
        if uid is None:
            continue
        out[uid] = {"champion": rid == champ_rid,
                    "runner_up": rid == runner_rid, "rounds_won": n}
    return out


def bracket_placements(
    bracket: list[dict],
    roster_to_user: dict[int, str],
) -> dict[str, dict]:
    """Per owner who played in a bracket: ``{place, champion, runner_up, rounds_won}``.

    ``place`` is the final 1-based finish *within this bracket*, read off the
    Sleeper placement games: a game with ``p == k`` sends its winner to place
    ``k`` and its loser to place ``k + 1`` (championship ``p == 1`` → 1st/2nd,
    ``p == 3`` → 3rd/4th, ...). Works identically for the winners bracket
    (place 1 = league champion) and the losers / toilet bracket (place 1 =
    toilet champion, i.e. the 1.01 draft pick in leagues where the toilet
    winner picks first).

    Unlike :func:`bracket_results`, this returns *every* roster that played a
    game — including first-round losers — so playoff participation is no longer
    lost. A roster eliminated before any placement game (rare brackets without
    full consolation games) gets ``place = None`` but is still present.
    """
    games = bracket or []
    participants: set[int] = set()
    place_by_rid: dict[int, int] = {}
    rounds_won: dict[int, int] = {}
    for g in games:
        for key in ("w", "l", "t1", "t2"):
            rid = g.get(key)
            if isinstance(rid, int):
                participants.add(rid)
        # Title-path wins (mirror bracket_results): advancement + championship.
        if g.get("p") in (None, 1):
            w = g.get("w")
            if isinstance(w, int):
                rounds_won[w] = rounds_won.get(w, 0) + 1
        p = g.get("p")
        if p is not None:
            w, l = g.get("w"), g.get("l")
            if isinstance(w, int):
                place_by_rid[w] = p
            if isinstance(l, int):
                place_by_rid[l] = p + 1
    out: dict[str, dict] = {}
    for rid in participants:
        uid = roster_to_user.get(rid)
        if uid is None:
            continue
        place = place_by_rid.get(rid)
        out[uid] = {
            "place": place,
            "champion": place == 1,
            "runner_up": place == 2,
            "rounds_won": rounds_won.get(rid, 0),
        }
    return out
