"""Data IO for GraderService — fetches matchups, KTC, FantasyCalc.

Lifted from sleeper_dynasty.cli._run_trades so the same logic powers
both the CLI and the API without duplication.
"""

from __future__ import annotations

import logging
from typing import Any

from sleeper_dynasty.api.fantasycalc import fetch_fantasycalc_values
from sleeper_dynasty.api.ktc import (
    build_pick_value_table, build_pick_value_table_tiered, fetch_ktc_values,
)
from sleeper_dynasty.cache import FileCache, ONE_DAY
from sleeper_dynasty.engine.nfl_actuals import score_week
from sleeper_dynasty.engine.playoff_phase import classify_playoff_phases
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.util.name_match import normalize_player_name

log = logging.getLogger(__name__)

_NFL_STATS_TTL_HISTORICAL = 10 ** 9  # completed weeks never change
_NFL_REGULAR_WEEKS = 18  # NFL regular season; pre-2021 weeks 18 just fetch empty

def is_redraft_chain(chain) -> bool:
    """Is this league redraft *now*? Judged by the latest season in the chain,
    so a league that converted formats is priced by where it currently is.
    An empty chain is never redraft — never demote without positive evidence.

    Reads ``League.format``, which every adapter populates, so this is
    platform-agnostic: a Yahoo redraft league prices the same way.
    """
    if not chain:
        return False
    latest = max(chain, key=lambda lg: lg.season)
    return getattr(latest, "format", "dynasty") == "redraft"


def _nfl_weeks_to_fetch(
    seasons,
    current_sw: tuple[int, int] | None = None,
    *,
    weeks_per_season: int = _NFL_REGULAR_WEEKS,
) -> list[tuple[int, int]]:
    """NFL (season, week) keys to fetch actuals for: weeks 1..18 per season.

    Derived from NFL weeks, NOT fantasy matchup weeks — the latter omit week 18,
    which would undercount drop windows crossing the season boundary. The
    in-progress season is capped at the current week so we never fetch the
    future (those weeks return empty anyway).
    """
    out: list[tuple[int, int]] = []
    for s in sorted(seasons):
        last = weeks_per_season
        if current_sw and s == current_sw[0]:
            last = min(weeks_per_season, current_sw[1])
        out.extend((s, w) for w in range(1, last + 1))
    return out


async def fetch_nfl_points(
    client,
    season_weeks: list[tuple[int, int]],
    scoring: dict[str, float],
    cache: "FileCache | None",
    *,
    current_sw: tuple[int, int] | None = None,
) -> dict[tuple[int, int], dict[str, float]]:
    """{(season, week): {player_id: league points}} for the given weeks.

    Raw stats cached league-agnostically per week; the current in-progress week
    uses a short TTL, completed weeks effectively never expire. A failed fetch
    contributes an empty week (0 for everyone), never raises.
    """
    out: dict[tuple[int, int], dict[str, float]] = {}
    for sw in season_weeks:
        season, week = sw
        key = f"nfl_stats_{season}_{week}.json"
        ttl = ONE_DAY if sw == current_sw else _NFL_STATS_TTL_HISTORICAL
        raw = cache.read(key, max_age_seconds=ttl) if cache is not None else None
        if raw is None:
            try:
                raw = await client.get_stats(season, week)
            except Exception as e:
                log.warning("NFL stats fetch failed for %s wk%s: %s", season, week, e)
                raw = {}
            # Never cache the in-progress week: its partial stats would freeze
            # under the historical TTL once the week completes. It's re-fetched
            # fresh every refresh until it's no longer the current week.
            if cache is not None and raw and sw != current_sw:
                cache.write(key, raw)
        out[sw] = score_week(raw or {}, scoring)
    return out


def _assemble_played_matchups(
    raw_per_week: dict[int, list[dict]],
    league_id: str,
) -> dict[tuple[str, int, int], dict]:
    """Pair Sleeper matchup entries by matchup_id and emit one dict per
    (league_id, week, roster_id) for PLAYED games only.

    Filters out placeholder data Sleeper returns for upcoming weeks
    (both sides zeroed).
    """
    out: dict[tuple[str, int, int], dict] = {}
    for week, raw in raw_per_week.items():
        by_matchup: dict[int, list[dict]] = {}
        for entry in raw:
            by_matchup.setdefault(entry.get("matchup_id"), []).append(entry)
        for entries in by_matchup.values():
            if len(entries) != 2:
                continue
            a, b = entries
            a_pts = a.get("points") or 0.0
            b_pts = b.get("points") or 0.0
            if a_pts == 0.0 and b_pts == 0.0:
                continue
            for x, y in ((a, b), (b, a)):
                out[(league_id, week, x["roster_id"])] = {
                    "starters": x.get("starters") or [],
                    "players": x.get("players") or [],
                    "players_points": x.get("players_points") or {},
                    "team_points": x.get("points"),
                    "opponent_points": y.get("points"),
                    "opponent_roster_id": y["roster_id"],
                }
    return out


async def _league_matchup_bundle(client, lg, league_cache) -> dict:
    """Build (or load from cache) the per-league matchup bundle.

    Sealed leagues (status == "complete") are loaded from / stored in
    ``league_cache``; the current season is always fetched and never cached.
    """
    sealed = league_cache is not None and getattr(lg, "status", None) == "complete"
    if sealed:
        cached = league_cache.read_matchup_bundle(lg.league_id)
        if cached is not None and "winners_bracket" in cached:
            return cached

    rosters = await client.get_rosters(lg.league_id)
    roster_to_user = {r.roster_id: r.owner_id for r in rosters}
    users = await client.get_users(lg.league_id)
    owners = {
        uid: {
            "owner_name": info.get("display_name") or uid,
            "team_name": info.get("team_name"),
            "avatar_url": info.get("avatar_url"),
        }
        for uid, info in users.items()
    }
    raw_per_week: dict[int, list[dict]] = {}
    for week in range(1, 19):
        raw_per_week[week] = await client.get_raw_matchups(lg.league_id, week)
    matchups = _assemble_played_matchups(raw_per_week, lg.league_id)

    winners = await client.get_winners_bracket(lg.league_id)
    losers = await client.get_losers_bracket(lg.league_id)

    bundle = {
        "matchups": matchups,
        "playoff_week_start": lg.playoff_week_start,
        "roster_to_user": roster_to_user,
        "roster_positions": list(getattr(lg, "roster_positions", []) or []),
        "league_name": lg.name,
        "season": lg.season,
        "owners": owners,
        "winners_bracket": winners,
        "losers_bracket": losers,
        "playoff_round_type": getattr(lg, "playoff_round_type", 0),
        "num_playoff_teams": getattr(lg, "num_playoff_teams", 0),
    }
    if sealed:
        if not winners and not losers:
            log.warning(
                "sealed league %s (season %s) has empty winners+losers brackets",
                lg.league_id, getattr(lg, "season", "?"),
            )
        league_cache.write_matchup_bundle(lg.league_id, bundle)
    return bundle


def resolve_ktc_to_player_id(
    ktc_values: dict[str, KTCValue], raw_players: dict
) -> dict[str, KTCValue]:
    """Map name-keyed KTC values onto Sleeper player_ids (KTC only, no FC)."""
    out: dict[str, KTCValue] = {}
    for pid, p in raw_players.items():
        if not isinstance(p, dict):
            continue
        full = (p.get("full_name") or
                f"{p.get('first_name','')} {p.get('last_name','')}".strip())
        v = ktc_values.get(normalize_player_name(full)) if full else None
        if v is not None:
            out[pid] = v
    return out


async def pull_supporting_data(
    client, chain, players=None, league_cache=None, snapshot_store=None,
) -> dict[str, Any]:
    """Walk the chain to assemble matchups, KTC, FantasyCalc, display names.

    Output keys match the GraderService.run contract.
    """
    warnings: list[str] = []

    redraft = is_redraft_chain(chain)

    # KTC is a dynasty valuation site with no redraft product, so a redraft
    # league sources player values from FantasyCalc's redraft set alone. Pick
    # value tables come out of the raw KTC blob and stay empty as a result.
    #
    # That matters far less than it sounds. Redraft leagues do trade picks on
    # Sleeper, but only current-season ones pre-draft — a next-year pick means
    # nothing when the roster resets — and `trade_history.py` resolves a pick
    # into the player it drafted once that draft completes. So the empty table
    # only bites in the window before the draft, and the warning below says so
    # rather than claiming picks are permanently worthless.
    ktc_values: dict[str, KTCValue] = {}
    if not redraft:
        try:
            ktc_values = await fetch_ktc_values()
        except Exception as e:
            log.warning("KTC unavailable: %s", e)
            warnings.append("KTC values unavailable")
            ktc_values = {}

    # Draft-pick values live in the raw, name-keyed KTC blob and would be
    # dropped by the player_id matching below. Capture them first.
    pick_value_table = build_pick_value_table(ktc_values)
    pick_value_table_tiered = build_pick_value_table_tiered(ktc_values)

    if snapshot_store is not None and ktc_values:
        from datetime import date
        snapshot_store.capture(ktc_values, date.today())

    try:
        fc_values = await fetch_fantasycalc_values(dynasty=not redraft)
    except Exception as e:
        log.warning("FantasyCalc unavailable: %s", e)
        warnings.append("FantasyCalc values unavailable")
        fc_values = {}

    raw_players = players if players is not None else await client.get_players()
    ktc_by_player_id: dict[str, KTCValue] = resolve_ktc_to_player_id(ktc_values, raw_players)

    fc_filled = 0
    for pid, fc in fc_values.items():
        if pid in ktc_by_player_id:
            continue
        sf = fc.get("superflex")
        one_qb = fc.get("one_qb")
        if sf is None and one_qb is None:
            continue
        p = raw_players.get(pid) if isinstance(raw_players.get(pid), dict) else None
        full = (p.get("full_name") if p else "") or pid
        ktc_by_player_id[pid] = KTCValue(
            name=full, normalized_name=full,
            position=(p.get("position") if p else "") or "",
            superflex_value=sf, one_qb_value=one_qb,
        )
        fc_filled += 1

    if redraft:
        # Start accruing redraft price history. The dynasty capture above is a
        # no-op here (ktc_values is empty by design), so today's FantasyCalc
        # redraft table is what gets stored — into the `redraft` namespace,
        # never the dynasty one. This cannot be backfilled: FantasyCalc has no
        # historical endpoint and capture() only writes today, so at-trade and
        # realized repricing light up for trades made from here forward and
        # stay unavailable for older ones.
        if snapshot_store is not None and ktc_by_player_id:
            from datetime import date as _date
            snapshot_store.capture(ktc_by_player_id, _date.today())

        # The redraft set is thinner than dynasty (~200 vs ~474 players) and
        # has no KTC backstop. Redraft leagues also do trade draft picks on
        # Sleeper (this isn't dynasty-only); with KTC skipped, picks price at
        # 0 until that season's draft resolves them. Disclose rather than
        # paper over. Redraft pick valuation is out of scope here.
        log.info("Redraft chain: %d players valued from FantasyCalc", fc_filled)
        warnings.append(
            "Redraft values cover roughly the top 200 players; deep bench "
            "and IDP players are unvalued. A traded draft pick shows no "
            "value until that season's draft, after which it is valued as "
            "the player it became"
        )
    else:
        log.info("FantasyCalc filled %d players KTC didn't rank", fc_filled)

    # Matchups + per-league meta.
    matchups: dict[tuple[str, int, int], dict] = {}
    playoff_weeks_by_league: dict[str, int] = {}
    playoff_week_start_by_league: dict[str, int] = {}
    phase_by_lwr: dict[tuple[str, int, int], str] = {}
    roster_to_user_by_league: dict[str, dict[int, str]] = {}
    roster_positions_by_league: dict[str, list] = {}
    league_name_by_id: dict[str, str] = {}
    league_season_by_id: dict[str, int] = {}
    winners_bracket_by_league: dict[str, list] = {}
    losers_bracket_by_league: dict[str, list] = {}
    num_playoff_teams_by_league: dict[str, int] = {}
    owners: dict[str, dict[str, Any]] = {}

    for lg in chain:
        b = await _league_matchup_bundle(client, lg, league_cache)
        league_name_by_id[lg.league_id] = b["league_name"]
        playoff_weeks_by_league[lg.league_id] = b["playoff_week_start"]
        playoff_week_start_by_league[lg.league_id] = b["playoff_week_start"]
        league_season_by_id[lg.league_id] = b["season"]
        roster_to_user_by_league[lg.league_id] = b["roster_to_user"]
        roster_positions_by_league[lg.league_id] = b.get("roster_positions", [])
        winners_bracket_by_league[lg.league_id] = b.get("winners_bracket") or []
        losers_bracket_by_league[lg.league_id] = b.get("losers_bracket") or []
        num_playoff_teams_by_league[lg.league_id] = b.get("num_playoff_teams", 0)
        for uid, ident in b["owners"].items():
            owners.setdefault(uid, ident)
        matchups.update(b["matchups"])
        for (wk, rid), ph in classify_playoff_phases(
            b.get("winners_bracket") or [],
            b.get("losers_bracket") or [],
            b["playoff_week_start"],
            b.get("playoff_round_type", 0),
        ).items():
            phase_by_lwr[(lg.league_id, wk, rid)] = ph

    # NFL-wide weekly actuals, scored to THIS league, for drop regret.
    current_sw = None
    try:
        st = await client.get_nfl_state()
        if st.get("season") and st.get("week"):
            current_sw = (int(st["season"]), int(st["week"]))
    except Exception:
        pass
    seasons = {
        league_season_by_id.get(lg, 0) for (lg, _wk, _rid) in matchups.keys()
    }
    seasons.discard(0)
    season_weeks = _nfl_weeks_to_fetch(seasons, current_sw)
    scoring = getattr(chain[0], "scoring_settings", {}) if chain else {}
    # Fall back to the configured cache dir, NOT to a re-imported
    # ``DEFAULT_CACHE_DIR``. A ``from … import`` copies the reference at import
    # time, so this module held its own binding that neither the engine-side
    # patch nor TRADE_GRADER_CACHE_DIR could reach — the same defect one layer
    # up, and the one place a bare-FileCache guard cannot see, because this
    # site always passes an argument, just the wrong one. Production always
    # supplies a real ``league_cache`` (grader.py), so this path is reached
    # only by callers that omit it.
    from app.config import get_settings
    nfl_cache = FileCache(
        getattr(league_cache, "cache_dir", None) or get_settings().cache_dir)
    try:
        nfl_points = await fetch_nfl_points(
            client, season_weeks, scoring, nfl_cache, current_sw=current_sw)
    except Exception as e:
        log.warning("NFL points unavailable: %s", e)
        nfl_points = {}

    # Player ages (current) from birth_date, for the GM-rating outlook signal.
    from datetime import date
    today = date.today()
    player_ages: dict[str, int] = {}
    for pid, p in raw_players.items():
        if not isinstance(p, dict):
            continue
        bd = p.get("birth_date")
        if not bd:
            continue
        try:
            y, m, d = (int(x) for x in str(bd).split("-")[:3])
            player_ages[pid] = today.year - y - ((today.month, today.day) < (m, d))
        except (ValueError, TypeError):
            continue

    return {
        "matchups": matchups,
        "ktc_by_player_id": ktc_by_player_id,
        "pick_value_table": pick_value_table,
        "pick_value_table_tiered": pick_value_table_tiered,
        "playoff_weeks_by_league": playoff_weeks_by_league,
        "playoff_week_start_by_league": playoff_week_start_by_league,
        "phase_by_lwr": phase_by_lwr,
        "roster_to_user_by_league": roster_to_user_by_league,
        "roster_positions_by_league": roster_positions_by_league,
        "league_name_by_id": league_name_by_id,
        "league_season_by_id": league_season_by_id,
        "winners_bracket_by_league": winners_bracket_by_league,
        "losers_bracket_by_league": losers_bracket_by_league,
        "num_playoff_teams_by_league": num_playoff_teams_by_league,
        "player_ages": player_ages,
        "nfl_points": nfl_points,
        "owners": owners,
        "owners_display": {uid: (o.get("owner_name") or uid)
                           for uid, o in owners.items()},
        "positions": {pid: raw.get("position")
                      for pid, raw in raw_players.items()
                      if isinstance(raw, dict)},
        "warnings": warnings,
    }
