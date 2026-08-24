"""Compute GM-rating pillar signals (outcomes + outlook) from refresh data.

Bridges the refresh ``supporting`` bundle to the pure engine extractors: per-season
standings + bracket results -> outcome signals; current roster KTC + ages -> outlook
signals. Draft capital + draft skill are computed from traded picks and
rookie-draft results threaded in from the refresh.
"""

from __future__ import annotations

from typing import Any

from sleeper_dynasty.engine.asset_signals import asset_signals
from sleeper_dynasty.engine.draft_signals import (
    DraftedPick, draft_skill, pick_holdings_value, strength_tiers,
)
from sleeper_dynasty.engine.gm_signals import (
    bracket_placements, bracket_results, outcome_signals,
)
from sleeper_dynasty.engine.results_signals import (
    latest_played_season as _latest_played_season, results_signals,
)
from sleeper_dynasty.engine.skill_signals import lineup_skill_signals
from sleeper_dynasty.engine.standings import all_play_win_pct, standings_as_of


def _ktc_value(v: Any, fmt: str = "superflex") -> float:
    if v is None:
        return 0.0
    raw = v.superflex_value if fmt == "superflex" else v.one_qb_value
    return float(raw) if raw is not None else 0.0


def compute_rating_signals(
    supporting: dict, current_holders: dict[str, str],
    *,
    traded_picks: list | None = None,
    rookie_picks: list[DraftedPick] | None = None,
    num_draft_rounds: int = 4,
    axis: str = "blend",
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]], dict[str, dict[str, float]], dict[str, dict[str, dict]]]:
    """Return ``(outcome_signals, outlook_signals)`` per owner uid."""
    matchups = supporting.get("matchups") or {}
    r2u_by_league = supporting.get("roster_to_user_by_league") or {}
    season_by_league = supporting.get("league_season_by_id") or {}
    pws_by_league = supporting.get("playoff_week_start_by_league") or {}
    wb_by_league = supporting.get("winners_bracket_by_league") or {}
    lb_by_league = supporting.get("losers_bracket_by_league") or {}
    npt_by_league = supporting.get("num_playoff_teams_by_league") or {}
    ktc = supporting.get("ktc_by_player_id") or {}
    ages = supporting.get("player_ages") or {}
    owners = list(supporting.get("owners") or {})

    # Per-season final standings + bracket results.
    standings_by_season: dict[int, list] = {}
    brackets_by_season: dict[int, dict] = {}        # winners bracket_results (GM rating)
    winners_place_by_season: dict[int, dict] = {}   # full winners placements (Finish col)
    losers_place_by_season: dict[int, dict] = {}    # toilet placements / draft order
    npt_by_season: dict[int, int] = {}
    all_play_by_season: dict[int, dict[str, float]] = {}
    for lg, season in season_by_league.items():
        r2u = r2u_by_league.get(lg, {})
        pws = int(pws_by_league.get(lg, 15))
        standings_by_season[int(season)] = standings_as_of(
            matchups, league_id=lg, through_week=pws - 1,
            playoff_week_start=pws, roster_to_user=r2u)
        all_play_by_season[int(season)] = all_play_win_pct(
            matchups, league_id=lg, playoff_week_start=pws, roster_to_user=r2u)
        brackets_by_season[int(season)] = bracket_results(
            wb_by_league.get(lg) or [], r2u)
        winners_place_by_season[int(season)] = bracket_placements(
            wb_by_league.get(lg) or [], r2u)
        losers_place_by_season[int(season)] = bracket_placements(
            lb_by_league.get(lg) or [], r2u)
        npt_by_season[int(season)] = int(npt_by_league.get(lg, 0))

    osig = outcome_signals(
        standings_by_season=standings_by_season,
        bracket_results_by_season=brackets_by_season,
        num_playoff_teams_by_season=npt_by_season,
        owners=owners)

    # Outlook: current roster value (KTC) + youth (avg age). Draft capital deferred.
    roster_value = {u: 0.0 for u in owners}
    age_sum = {u: 0.0 for u in owners}
    age_n = {u: 0 for u in owners}
    for pid, uid in current_holders.items():
        roster_value.setdefault(uid, 0.0)
        age_sum.setdefault(uid, 0.0)
        age_n.setdefault(uid, 0)
        roster_value[uid] += _ktc_value(ktc.get(pid))
        if pid in ages:
            age_sum[uid] += ages[pid]
            age_n[uid] += 1

    # --- Draft capital: KTC value of future picks held (current league). ---
    current_league = max(season_by_league, key=lambda lg: season_by_league[lg]) \
        if season_by_league else None
    r2u_current = r2u_by_league.get(current_league, {}) if current_league else {}
    current_season = max((int(s) for s in season_by_league.values()), default=0)
    outlook_seasons = [current_season + 1, current_season + 2, current_season + 3]
    pick_values = {
        k: _ktc_value(v) for k, v in (supporting.get("pick_value_table") or {}).items()
    }
    roster_value_by_id = {
        rid: roster_value.get(uid, 0.0) for rid, uid in r2u_current.items()
    }
    tier_by_roster = strength_tiers(roster_value_by_id)
    tiered_pick_values = {
        k: _ktc_value(v)
        for k, v in (supporting.get("pick_value_table_tiered") or {}).items()
    }
    holdings = pick_holdings_value(
        traded_picks=traded_picks or [], roster_ids=list(r2u_current),
        seasons=outlook_seasons, num_rounds=num_draft_rounds, pick_values=pick_values,
        tier_by_roster=tier_by_roster, tiered_values=tiered_pick_values)
    draft_capital_by_uid: dict[str, float] = {}
    for rid, dval in holdings.items():
        uid = r2u_current.get(rid)
        if uid:
            draft_capital_by_uid[uid] = draft_capital_by_uid.get(uid, 0.0) + dval

    # --- Draft skill: how past rookie picks panned out vs their slot tier. ---
    production_by_player: dict[str, float] = {}
    games_by_player: dict[str, int] = {}
    for entry in matchups.values():
        for pid, pts in (entry.get("players_points") or {}).items():
            pts_f = float(pts)
            production_by_player[pid] = production_by_player.get(pid, 0.0) + pts_f
            # Points > 0 means the player actually played that week (IR players
            # appear in players_points at 0.0, so >0 is the "played" convention).
            if pts_f > 0:
                games_by_player[pid] = games_by_player.get(pid, 0) + 1
    ktc_floats = {pid: _ktc_value(v) for pid, v in ktc.items()}
    draft_skill_by_uid = draft_skill(
        picks=rookie_picks or [], ktc_by_player=ktc_floats,
        production_by_player=production_by_player,
        games_by_player=games_by_player, min_games=17, axis=axis)

    olsig: dict[str, dict[str, float]] = {}
    for u in roster_value:
        avg_age = age_sum[u] / age_n[u] if age_n[u] else 0.0
        olsig[u] = {
            "roster_value": roster_value[u],
            "draft_capital": draft_capital_by_uid.get(u, 0.0),
            "draft_skill": draft_skill_by_uid.get(u, 0.0),
            "youth": -avg_age,
        }

    # v2 Assets: current-roster shares (scale-free, unlike raw roster_value).
    # Merged into the same dict rather than replacing it -- see the v2 Results
    # comment below for why both generations of keys are kept.
    assets = asset_signals(
        current_holders=current_holders, value_by_player=ktc_floats,
        age_by_player=ages, owners=owners)
    for uid, sigs in assets.items():
        olsig.setdefault(uid, {}).update(sigs)

    # Per-season draft skill (for year-scoped Draft Ace KPI card).
    draft_seasons = sorted({p.draft_season for p in (rookie_picks or []) if p.draft_season})
    season_draft_skill: dict[str, dict[str, float]] = {}
    for season in draft_seasons:
        s_picks = [p for p in (rookie_picks or []) if p.draft_season == season]
        if s_picks:
            season_draft_skill[str(season)] = draft_skill(
                picks=s_picks,
                ktc_by_player=ktc_floats,
                production_by_player=production_by_player,
                games_by_player=games_by_player, min_games=17, axis=axis)

    # Per-season W-L records + playoff finishes (for the Record dashboard column).
    # Authoritative team count per season from the actual roster mapping,
    # not len(rows) which can include phantom roster entries from chain walks.
    season_to_total: dict[int, int] = {
        int(season): len(r2u_by_league.get(lg, {}))
        for lg, season in season_by_league.items()
    }

    season_records: dict[str, dict[str, dict]] = {}
    for season, rows in standings_by_season.items():
        total_teams = season_to_total.get(season, len(rows))
        season_brackets = brackets_by_season.get(season, {})
        winners_place = winners_place_by_season.get(season, {})
        losers_place = losers_place_by_season.get(season, {})
        season_records[str(season)] = {}
        # Filter out phantom roster entries: a real team in a completed season always
        # has at least 1 game played (wins + losses + ties > 0). Phantoms have 0-0-0.
        real_rows = [
            row for row in rows
            if row.wins + row.losses + row.ties > 0
        ]
        # Re-rank among real teams only (phantoms excluded).
        real_total = len(real_rows)
        for rank_idx, row in enumerate(real_rows):
            uid = row.owner_id
            if uid in season_records[str(season)]:
                continue  # keep first-seen entry for uid
            br = season_brackets.get(uid, {})
            rounds_won = int(br.get("rounds_won") or 0)
            # Full bracket placements: participation is now keyed off appearing in
            # the bracket at all (not rounds_won > 0), so first-round exits count.
            wp = winners_place.get(uid)
            lp = losers_place.get(uid)
            playoff_place = wp.get("place") if wp else None
            toilet_place = lp.get("place") if lp else None
            season_records[str(season)][uid] = {
                "wins": row.wins,
                "losses": row.losses,
                "ties": row.ties,
                "rank": rank_idx + 1,       # 1-based reg-season rank among real teams
                "total_teams": real_total,
                "champion": bool(br.get("champion")),
                "runner_up": bool(br.get("runner_up")),
                "made_playoffs": wp is not None,        # participated in winners bracket
                "rounds_won": rounds_won,               # playoff wins (title path)
                "playoff_place": playoff_place,         # 1=champ … 6th (winners bracket)
                "made_toilet": lp is not None,          # participated in losers bracket
                "toilet_place": toilet_place,           # 1=toilet champ -> 1.01 pick
            }

    # v2 Results. Merged into the same dict rather than replacing it: v1's keys
    # have three non-scoring consumers (grader._playoff_rate_by_uid, and
    # gm_rating_blurb twice), and compute_gm_ratings only reads the keys named
    # in its signal_weights, so carrying both costs nothing. Built from
    # season_records (already assembled just above) rather than a second
    # near-identical dict -- results_signals wants int season keys and
    # season_records is keyed by str(season), so convert here.
    #
    # season_records' made_playoffs means "participated in the winners
    # bracket" (a fact from the actual bracket), not the rank <= playoff_teams
    # reconstruction outcome_signals uses -- deliberately, so the grade never
    # disagrees with what the Track Record tab shows for the same season.
    records_for_results = {
        int(season): rows for season, rows in season_records.items()
    }
    anchor = _latest_played_season(records_for_results)
    if anchor is not None:
        rsig = results_signals(
            all_play_by_season=all_play_by_season,
            season_records=records_for_results,
            owners=owners, latest_played_season=anchor)
        for uid, sigs in rsig.items():
            osig.setdefault(uid, {}).update(sigs)

    return osig, olsig, season_draft_skill, season_records


def compute_lineup_signals(
    supporting: dict, owners: list[str]
) -> dict[str, dict[str, float]]:
    """Per-owner lineup efficiency from the refresh ``supporting`` bundle.

    Degrades to zeros (never raises) when the bundle predates
    ``roster_positions_by_league`` so a wiring gap can't break refresh.
    """
    return lineup_skill_signals(
        matchups=supporting.get("matchups") or {},
        roster_positions_by_league=supporting.get("roster_positions_by_league") or {},
        positions=supporting.get("positions") or {},
        roster_to_user_by_league=supporting.get("roster_to_user_by_league") or {},
        owners=list(owners),
    )
