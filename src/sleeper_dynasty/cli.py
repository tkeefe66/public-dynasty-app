"""Command-line orchestrator for Sleeper dynasty analysis.

Wires together the Sleeper API client, projections, caching, simulator,
dynasty outlook engine, and HTML report output to produce a complete
dynasty league report from a single ``analyze <username>`` invocation.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any

import anthropic

from sleeper_dynasty.api.fantasycalc import fetch_fantasycalc_values
from sleeper_dynasty.api.ktc import build_pick_value_table, fetch_ktc_values
from sleeper_dynasty.api.nfl_schedule import fetch_week_schedule, derive_byes
from sleeper_dynasty.api.projections import (
    blend_projections,
    fetch_fantasypros_projections,
    normalize_projection,
)
from sleeper_dynasty.api.sleeper import SleeperClient
from sleeper_dynasty.api.weather import fetch_game_weather
from sleeper_dynasty.cache import FileCache
from sleeper_dynasty.engine.dynasty import build_dynasty_outlook
from sleeper_dynasty.engine.lineup import solve_optimal_lineup
from sleeper_dynasty.engine.outlook import build_outlook_facts
from sleeper_dynasty.engine.recap import build_recap_facts
from sleeper_dynasty.engine.simulator import simulate_season
from sleeper_dynasty.engine.playoff_phase import classify_playoff_phases
from sleeper_dynasty.engine.trade_grader import (
    aggregate_owner_records,
    grade_trade,
)
from sleeper_dynasty.engine.trade_history import build_trade_history
from sleeper_dynasty.models.player import (
    FantasyProsProjection,
    KTCValue,
    Player,
    PlayerProjection,
    build_players as _build_players,
)
from sleeper_dynasty.llm.recap_writer import RecapWriter
from sleeper_dynasty.output.google_docs import GoogleDocsReport
from sleeper_dynasty.output.html_report import HTMLReport
from sleeper_dynasty.output.recap_render import HtmlFileDelivery
from sleeper_dynasty.util.name_match import normalize_player_name

logger = logging.getLogger(__name__)

# Leagues in these statuses are considered dynasty-relevant.
DYNASTY_LEAGUE_STATUSES = {"in_season", "pre_draft", "drafting", "complete"}

# Default regular-season length used when filling in matchups schedule.
_DEFAULT_REGULAR_SEASON_END = 14

# Players cache key.
_PLAYERS_CACHE_KEY = "players_nfl.json"

# FantasyPros / KTC / FantasyCalc cache keys. Stored as JSON-serialized
# lists of the dataclass to_dict() outputs so they round-trip cleanly
# through FileCache.
_FANTASYPROS_CACHE_KEY = "fantasypros_{season}.json"
_KTC_CACHE_KEY = "ktc_values.json"
_FANTASYCALC_CACHE_KEY = "fantasycalc_values.json"

# Cache keys for the trades feature.
_TRANSACTIONS_CACHE_KEY = "transactions_{league_id}_w{week}.json"
_DRAFTS_CACHE_KEY = "drafts_{league_id}.json"
_DRAFT_PICKS_CACHE_KEY = "draft_picks_{draft_id}.json"
_MATCHUPS_CACHE_KEY = "matchups_{league_id}_w{week}.json"
_LEAGUE_META_CACHE_KEY = "league_meta_{league_id}.json"
_USERS_CACHE_KEY = "users_{league_id}.json"

# Effectively-infinite TTL for historical (completed-season) data.
_ONE_YEAR_SECONDS = 365 * 24 * 3600


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]`` when None).

    Returns:
        Parsed ``argparse.Namespace`` with a ``command`` attribute and the
        analyze-specific flags.
    """
    parser = argparse.ArgumentParser(
        prog="sleeper-dynasty",
        description="Dynasty league analyzer for Sleeper.",
    )
    subparsers = parser.add_subparsers(dest="command")

    analyze = subparsers.add_parser(
        "analyze", help="Analyze a user's dynasty league(s)."
    )
    analyze.add_argument("username", help="Sleeper username to analyze.")
    analyze.add_argument(
        "--season", type=int, default=2026, help="NFL season (default: 2026)."
    )
    analyze.add_argument(
        "--week",
        type=int,
        default=1,
        help="Starting week to simulate from (default: 1).",
    )
    analyze.add_argument(
        "--sims",
        type=int,
        default=10000,
        help="Number of Monte Carlo simulations (default: 10000).",
    )
    analyze.add_argument(
        "--no-cache",
        action="store_true",
        help="Invalidate all caches before running.",
    )

    trades = subparsers.add_parser(
        "trades",
        help="Build a Google Doc grading every historical trade in the user's "
             "dynasty league chain.",
    )
    trades.add_argument("username", help="Sleeper username.")
    trades.add_argument(
        "--season",
        type=int,
        default=2026,
        help="Entry-point season; we walk back from this season's league "
             "(default: 2026).",
    )
    trades.add_argument(
        "--no-cache",
        action="store_true",
        help="Invalidate all caches before running.",
    )
    trades.add_argument(
        "--refresh-trades",
        action="store_true",
        help="Invalidate only the trade/draft/matchup caches; keep player "
             "and KTC caches intact.",
    )
    trades.add_argument(
        "--private",
        action="store_true",
        help="Keep the generated Google Doc private.",
    )

    recap = subparsers.add_parser(
        "recap",
        help="Generate a savage weekly recap (and, later, outlook).",
    )
    recap.add_argument("username", help="Sleeper username.")
    recap.add_argument(
        "--season", type=int, default=2025,
        help="NFL season (default: 2025).",
    )
    recap.add_argument(
        "--week", type=int, default=None,
        help="Week to recap (default: last completed week per Sleeper state).",
    )
    recap.add_argument(
        "--lore", default=None,
        help="Path to a league_lore markdown file to feed the writer.",
    )
    recap.add_argument(
        "--persona", default=None,
        help="Path to a persona prompt override (default: built-in Analyst).",
    )
    recap.add_argument(
        "--model", default="claude-opus-4-8",
        help="Anthropic model id (default: claude-opus-4-8).",
    )
    recap.add_argument(
        "--out", default=None,
        help="Output HTML path (default: <league>_week<N>_recap.html in cwd).",
    )
    recap.add_argument(
        "--no-cache", action="store_true",
        help="Invalidate all caches before running.",
    )
    recap.add_argument(
        "--init-lore", metavar="PATH", default=None,
        help="Write a starter league-lore template to PATH and exit.",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def _write_lore_template(path: Path) -> str:
    """Write the starter league-lore template to ``path`` and return it."""
    from sleeper_dynasty.llm.recap_writer import load_lore_template
    path = Path(path)
    path.write_text(load_lore_template())
    logger.info("Wrote lore template to %s", path)
    return str(path)


def _select_league(leagues: list) -> Any:
    """Prompt the user to choose a league if there's more than one."""
    if len(leagues) == 1:
        return leagues[0]
    print("\nMultiple dynasty-relevant leagues found:")
    for idx, lg in enumerate(leagues, start=1):
        print(f"  [{idx}] {lg.name} ({lg.season}, {lg.status})")
    while True:
        choice = input(f"Select a league [1-{len(leagues)}]: ").strip()
        try:
            i = int(choice)
            if 1 <= i <= len(leagues):
                return leagues[i - 1]
        except ValueError:
            pass
        print("Invalid selection, try again.")


def _assemble_played_matchups(
    raw_per_week: dict[int, list[dict]],
    league_id: str,
) -> dict[tuple[str, int, int], dict]:
    """Pair Sleeper matchup entries by matchup_id and emit one dict
    entry per (league_id, week, roster_id) for played games only.

    Sleeper returns placeholder matchup data for upcoming weeks of the
    in-progress season — points=0 on both sides, placeholder starter list
    reflecting the manager's current lineup, players_points all 0. This
    filter excludes those so downstream points figures only reflect
    played games.

    Two NFL fantasy lineups totaling exactly 0 points in a real played game
    is functionally impossible — we use BOTH-zero as the unplayed sentinel.
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
            # Skip placeholder/unplayed weeks. Sleeper returns matchup
            # entries for upcoming weeks of the in-progress season with
            # points=0 on both sides. Counting those would inflate
            # Starter Wks / Playoff Starts on offseason trades.
            if a_pts == 0.0 and b_pts == 0.0:
                continue
            out[(league_id, week, a["roster_id"])] = {
                "starters": a.get("starters") or [],
                "players": a.get("players") or [],
                "players_points": a.get("players_points") or {},
                "team_points": a.get("points"),
                "opponent_points": b.get("points"),
                "opponent_roster_id": b["roster_id"],
            }
            out[(league_id, week, b["roster_id"])] = {
                "starters": b.get("starters") or [],
                "players": b.get("players") or [],
                "players_points": b.get("players_points") or {},
                "team_points": b.get("points"),
                "opponent_points": a.get("points"),
                "opponent_roster_id": a["roster_id"],
            }
    return out


def _compute_position_rankings(
    rosters: list,
    players: dict[str, Player],
    player_projections: dict[str, tuple[str, float]],
) -> dict[str, list[str]]:
    """Build position -> ordered player_id list (best first) across the league.

    Args:
        rosters: All rosters in the league.
        players: player_id -> Player.
        player_projections: player_id -> (position, projected_points).

    Returns:
        Dict mapping position string to list of player_ids ranked best-to-worst
        by projected points.
    """
    by_position: dict[str, list[tuple[str, float]]] = {}
    for roster in rosters:
        for pid in roster.players:
            if pid not in player_projections:
                continue
            pos, proj = player_projections[pid]
            if not pos:
                continue
            by_position.setdefault(pos, []).append((pid, proj))

    rankings: dict[str, list[str]] = {}
    for pos, entries in by_position.items():
        entries.sort(key=lambda x: x[1], reverse=True)
        rankings[pos] = [pid for pid, _ in entries]
    return rankings


def _compute_team_position_totals(
    rosters: list,
    player_projections: dict[str, tuple[str, float]],
) -> dict[int, dict[str, float]]:
    """Sum projected points by position for each roster."""
    totals: dict[int, dict[str, float]] = {}
    for roster in rosters:
        pos_totals: dict[str, float] = {}
        for pid in roster.players:
            if pid not in player_projections:
                continue
            pos, proj = player_projections[pid]
            if not pos:
                continue
            pos_totals[pos] = pos_totals.get(pos, 0.0) + proj
        totals[roster.roster_id] = pos_totals
    return totals


# ---------------------------------------------------------------------------
# Cached external-source fetchers
# ---------------------------------------------------------------------------


async def _load_fantasypros(
    cache: FileCache,
    season: int,
    use_cache: bool,
) -> dict[str, FantasyProsProjection]:
    """Fetch FantasyPros projections, populating / reading the day cache.

    Returns an empty dict on any failure — the caller treats that as a
    graceful degradation and falls back to Sleeper-only projections.
    """
    key = _FANTASYPROS_CACHE_KEY.format(season=season)
    if use_cache:
        cached = cache.read(key)
        if isinstance(cached, list):
            try:
                projs = [FantasyProsProjection.from_dict(d) for d in cached]
                logger.info(
                    "Loaded %d FantasyPros projections from cache", len(projs)
                )
                return {p.normalized_name: p for p in projs}
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    "FantasyPros cache unreadable (%s); refetching", e
                )

    try:
        projs = await fetch_fantasypros_projections(season)
    except Exception as e:
        # fetch_fantasypros_projections already logs HTTP errors; this
        # is a safety net for anything truly unexpected.
        logger.warning("FantasyPros projections unavailable: %s", e)
        return {}

    if projs:
        cache.write(key, [p.to_dict() for p in projs.values()])
    return projs


async def _load_ktc(
    cache: FileCache,
    use_cache: bool,
) -> dict[str, KTCValue]:
    """Fetch KTC dynasty values, populating / reading the day cache."""
    if use_cache:
        cached = cache.read(_KTC_CACHE_KEY)
        if isinstance(cached, list):
            try:
                values = [KTCValue.from_dict(d) for d in cached]
                logger.info("Loaded %d KTC values from cache", len(values))
                return {v.normalized_name: v for v in values}
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("KTC cache unreadable (%s); refetching", e)

    try:
        values = await fetch_ktc_values()
    except Exception as e:
        logger.warning("KTC values unavailable: %s", e)
        return {}

    if values:
        cache.write(_KTC_CACHE_KEY, [v.to_dict() for v in values.values()])
    return values


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


async def _run_analysis(args: argparse.Namespace) -> None:
    """Execute the full analysis pipeline for one Sleeper user."""
    cache = FileCache()
    if args.no_cache:
        logger.info("Invalidating cache (--no-cache)")
        cache.invalidate_all()

    client = SleeperClient()
    try:
        # 1. Resolve user.
        logger.info("Resolving user id for username=%s", args.username)
        user_id = await client.get_user_id(args.username)

        # 2. Fetch leagues for season and filter to dynasty-relevant statuses.
        leagues = await client.get_leagues(user_id, args.season)
        if not leagues:
            print(f"No leagues found for {args.username} in {args.season}.")
            return

        relevant = [lg for lg in leagues if lg.status in DYNASTY_LEAGUE_STATUSES]
        if not relevant:
            print(
                f"No dynasty-relevant leagues found for {args.username} "
                f"in {args.season} (statuses: "
                f"{sorted({lg.status for lg in leagues})})."
            )
            return

        league = _select_league(relevant)
        logger.info("Analyzing league: %s (%s)", league.name, league.league_id)

        # 3. Fetch rosters, traded picks, and weekly matchups.
        rosters = await client.get_rosters(league.league_id)
        traded_picks = await client.get_traded_picks(league.league_id)

        regular_season_end = league.playoff_week_start - 1
        matchups_by_week: dict[int, list] = {}
        for week in range(args.week, regular_season_end + 1):
            matchups_by_week[week] = await client.get_matchups(
                league.league_id, week
            )

        # 4. Load players (cached when possible).
        raw_players: dict[str, Any] | None = None
        if not args.no_cache:
            cached = cache.read(_PLAYERS_CACHE_KEY)
            if isinstance(cached, dict):
                raw_players = cached
                logger.info("Loaded players from cache")
        if raw_players is None:
            logger.info("Fetching players from Sleeper")
            raw_players = await client.get_players()
            cache.write(_PLAYERS_CACHE_KEY, raw_players)

        players = _build_players(raw_players)

        # 5. Fetch Sleeper projections; normalize to fantasy points using
        #    the league's scoring settings.
        #
        #    Sleeper (and FantasyPros) return SEASON-TOTAL stat projections.
        #    The simulator samples a per-week mean each week and sums across
        #    weeks, so we must convert season totals to per-week means by
        #    dividing by the number of regular-season weeks. Otherwise the
        #    simulated scores would be inflated by ~regular_season_weeks x.
        reg_season_weeks = league.playoff_week_start - 1
        logger.info("Fetching Sleeper projections for season %d", args.season)
        raw_sleeper_proj = await client.get_projections(args.season)
        sleeper_projections: dict[str, PlayerProjection] = {}
        for pid, stats in raw_sleeper_proj.items():
            if not isinstance(stats, dict):
                continue
            season_pts = normalize_projection(stats, league.scoring_settings)
            weekly_pts = (
                season_pts / reg_season_weeks
                if reg_season_weeks > 0
                else season_pts
            )
            sleeper_projections[pid] = PlayerProjection(
                player_id=pid,
                source="sleeper",
                season=args.season,
                week=None,
                projected_points=weekly_pts,
                stats=stats,
            )

        # 6. Fetch external FantasyPros projections (with daily cache).
        #    FantasyPros returns SEASON-TOTAL stat projections. We
        #    re-normalize them against the LEAGUE's scoring settings
        #    (so a half-PPR league doesn't get a full-PPR number) and
        #    then convert to a per-week mean for the simulator.
        fp_projections = await _load_fantasypros(
            cache, args.season, use_cache=not args.no_cache
        )

        external_by_norm_name: dict[str, PlayerProjection] = {}
        for norm_name, fp in fp_projections.items():
            league_season_pts = normalize_projection(
                fp.stats, league.scoring_settings
            )
            # Some leagues don't score every stat FP reports. If the
            # re-normalized total comes back as 0 but FP reported PPR
            # points, the league probably uses a quirky scoring scheme.
            # In that case prefer the FP PPR total over a zero — better
            # to blend something than to throw the FP signal away.
            if league_season_pts == 0 and fp.projected_points_ppr > 0:
                league_season_pts = fp.projected_points_ppr
            weekly_pts = (
                league_season_pts / reg_season_weeks
                if reg_season_weeks > 0
                else league_season_pts
            )
            external_by_norm_name[norm_name] = PlayerProjection(
                player_id="",
                source="fantasypros",
                season=args.season,
                week=None,
                projected_points=weekly_pts,
                stats=fp.stats,
            )

        # 7. Blend projections by matching on NORMALIZED player names —
        #    the actual fix to the broken exact-string-match.
        player_projections: dict[str, tuple[str, float]] = {}
        fp_match_count = 0
        for pid, sleeper_proj in sleeper_projections.items():
            player = players.get(pid)
            if player is None or not player.position:
                continue
            external = external_by_norm_name.get(
                normalize_player_name(player.full_name)
            )
            if external is not None:
                fp_match_count += 1
            blended = blend_projections(sleeper_proj, external)
            player_projections[pid] = (player.position, blended.projected_points)

        # Compute the rostered-player set up front: the denominator that
        # actually matters for users is "how many of MY league's players
        # got matched", not "how many of Sleeper's 10K+ players got matched".
        rostered_player_ids = {
            pid for roster in rosters for pid in roster.players
        }

        if fp_projections:
            logger.debug(
                "FantasyPros matched %d / %d Sleeper players (full DB)",
                fp_match_count,
                len(sleeper_projections),
            )
            fp_matched_rostered: list[str] = []
            fp_unmatched_rostered: list[str] = []
            for pid in rostered_player_ids:
                player = players.get(pid)
                if player is None:
                    continue
                if normalize_player_name(player.full_name) in external_by_norm_name:
                    fp_matched_rostered.append(player.full_name)
                else:
                    fp_unmatched_rostered.append(player.full_name)
            total_rostered_with_data = len(fp_matched_rostered) + len(
                fp_unmatched_rostered
            )
            logger.info(
                "FantasyPros matched %d / %d rostered players in your league",
                len(fp_matched_rostered),
                total_rostered_with_data,
            )
            if fp_unmatched_rostered:
                shown = sorted(fp_unmatched_rostered)[:10]
                extra = len(fp_unmatched_rostered) - len(shown)
                suffix = f", ...and {extra} more" if extra > 0 else ""
                logger.info(
                    "FantasyPros unmatched rostered: %s%s",
                    ", ".join(shown),
                    suffix,
                )

        # 7b. Fetch KTC dynasty values and match to player_ids by
        #     normalized name. NOT yet wired into the dynasty outlook
        #     engine — that's a planned follow-up. We just want the data
        #     plumbed and matched so we can see the join rate.
        ktc_values = await _load_ktc(cache, use_cache=not args.no_cache)
        ktc_by_player_id: dict[str, KTCValue] = {}
        for pid, player in players.items():
            ktc = ktc_values.get(normalize_player_name(player.full_name))
            if ktc is not None:
                ktc_by_player_id[pid] = ktc
        if ktc_values:
            logger.debug(
                "KTC matched %d / %d Sleeper players (full DB)",
                len(ktc_by_player_id),
                len(players),
            )
            ktc_matched_rostered: list[str] = []
            ktc_unmatched_rostered: list[str] = []
            for pid in rostered_player_ids:
                player = players.get(pid)
                if player is None:
                    continue
                if pid in ktc_by_player_id:
                    ktc_matched_rostered.append(player.full_name)
                else:
                    ktc_unmatched_rostered.append(player.full_name)
            total_rostered_with_data = len(ktc_matched_rostered) + len(
                ktc_unmatched_rostered
            )
            logger.info(
                "KTC matched %d / %d rostered players in your league",
                len(ktc_matched_rostered),
                total_rostered_with_data,
            )
            if ktc_unmatched_rostered:
                shown = sorted(ktc_unmatched_rostered)[:10]
                extra = len(ktc_unmatched_rostered) - len(shown)
                suffix = f", ...and {extra} more" if extra > 0 else ""
                logger.info(
                    "KTC unmatched rostered: %s%s",
                    ", ".join(shown),
                    suffix,
                )

        # 8. Run the Monte Carlo simulation.
        logger.info(
            "Running simulation: %d sims starting week %d",
            args.sims,
            args.week,
        )
        sim_result = simulate_season(
            league=league,
            rosters=rosters,
            matchups_by_week=matchups_by_week,
            player_projections=player_projections,
            start_week=args.week,
            num_sims=args.sims,
        )

        # 9. Build dynasty outlooks for each roster.
        position_rankings = _compute_position_rankings(
            rosters, players, player_projections
        )
        team_pos_totals = _compute_team_position_totals(
            rosters, player_projections
        )

        dynasty_outlooks = {}
        for roster in rosters:
            roster_players = [
                players[pid] for pid in roster.players if pid in players
            ]
            outlook = build_dynasty_outlook(
                roster=roster,
                roster_players=roster_players,
                traded_picks=traded_picks,
                position_rankings=position_rankings,
                total_rosters=league.total_rosters,
                num_rounds=4,
            )
            dynasty_outlooks[roster.roster_id] = outlook

        # 10. Build the self-contained HTML report.
        player_names = {pid: p.full_name for pid, p in players.items()}
        today = date.today()
        player_ages = {pid: p.age(as_of=today) for pid, p in players.items()}

        report = HTMLReport(league_name=league.name, season=league.season)
        report_path = report.generate(
            league=league,
            rosters=rosters,
            sim_result=sim_result,
            dynasty_outlooks=dynasty_outlooks,
            player_projections=player_projections,
            player_names=player_names,
            player_ages=player_ages,
        )

        # Open the generated file in the user's default browser. Use a
        # ``file://`` URL so the OS resolves it to the local renderer
        # rather than passing the raw path as an argv string.
        file_url = f"file://{report_path.resolve()}"
        logger.info("Opening report in browser: %s", file_url)
        webbrowser.open(file_url)
        print(f"\nReport ready: {report_path}")
    finally:
        await client.close()


async def _run_trades(args: argparse.Namespace) -> None:
    """Execute the trades pipeline: walk chain, grade trades, emit doc."""
    cache = FileCache()
    if args.no_cache:
        logger.info("Invalidating all caches (--no-cache)")
        cache.invalidate_all()
    if args.refresh_trades:
        # Best-effort: invalidate any cached transactions/drafts/matchups.
        for f in list(cache.cache_dir.iterdir()):
            name = f.name
            if (
                name.startswith("transactions_")
                or name.startswith("drafts_")
                or name.startswith("draft_picks_")
                or name.startswith("matchups_")
            ):
                cache.invalidate(name)

    client = SleeperClient()
    try:
        logger.info("Resolving user id for username=%s", args.username)
        user_id = await client.get_user_id(args.username)

        leagues = await client.get_leagues(user_id, args.season)
        if not leagues:
            print(f"No leagues found for {args.username} in {args.season}.")
            return
        relevant = [lg for lg in leagues if lg.status in DYNASTY_LEAGUE_STATUSES]
        if not relevant:
            print(
                f"No dynasty-relevant leagues for {args.username} in {args.season}."
            )
            return
        league = _select_league(relevant)
        logger.info("Building trade history starting from %s", league.league_id)

        # Load players once for asset display names.
        raw_players: Any | None = None
        cached = cache.read(_PLAYERS_CACHE_KEY)
        if isinstance(cached, dict):
            raw_players = cached
        if raw_players is None:
            raw_players = await client.get_players()
            cache.write(_PLAYERS_CACHE_KEY, raw_players)
        player_names = {
            pid: (
                raw.get("full_name")
                or f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip()
                or pid
            )
            for pid, raw in raw_players.items()
            if isinstance(raw, dict)
        }

        resolved_trades = await build_trade_history(
            client,
            current_league_id=league.league_id,
            player_names=player_names,
        )
        logger.info("Resolved %d trades", len(resolved_trades))

        # KTC values for snapshot lens — keyed by player_id for grader.
        ktc_values = await _load_ktc(cache, use_cache=not args.no_cache)
        # Draft-pick values live in the raw, name-keyed KTC blob and would be
        # dropped by the player_id matching below. Capture them first so the
        # snapshot lens can value undrafted future picks.
        pick_value_table = build_pick_value_table(ktc_values)
        ktc_by_player_id: dict[str, KTCValue] = {}
        for pid, p in raw_players.items():
            if not isinstance(p, dict):
                continue
            full_name = (
                p.get("full_name")
                or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            )
            v = ktc_values.get(normalize_player_name(full_name)) if full_name else None
            if v is not None:
                ktc_by_player_id[pid] = v

        # FantasyCalc fallback — fills gaps for players KTC doesn't rank
        # (KTC caps its dynasty rankings at ~500 players). FantasyCalc
        # returns Sleeper IDs directly so no name normalization is needed.
        # KTC entries always win; we only add to ktc_by_player_id when
        # the player is absent from KTC.
        fc_values: dict[str, dict[str, int]] = {}
        cached_fc = cache.read(_FANTASYCALC_CACHE_KEY)
        if isinstance(cached_fc, dict) and not args.no_cache:
            fc_values = {
                str(pid): {k: int(v) for k, v in vals.items()}
                for pid, vals in cached_fc.items()
                if isinstance(vals, dict)
            }
        if not fc_values:
            try:
                fc_values = await fetch_fantasycalc_values()
                if fc_values:
                    cache.write(_FANTASYCALC_CACHE_KEY, fc_values)
            except Exception as e:
                logger.warning("FantasyCalc unavailable: %s", e)
                fc_values = {}

        fc_filled = 0
        for pid, fc in fc_values.items():
            if pid in ktc_by_player_id:
                continue  # KTC wins
            sf = fc.get("superflex")
            one_qb = fc.get("one_qb")
            if sf is None and one_qb is None:
                continue
            p = raw_players.get(pid) if isinstance(raw_players.get(pid), dict) else None
            full_name = (
                (p.get("full_name") if p else None)
                or pid
            )
            position = (p.get("position") if p else "") or ""
            ktc_by_player_id[pid] = KTCValue(
                name=full_name,
                normalized_name=full_name,
                position=position,
                superflex_value=sf,
                one_qb_value=one_qb,
            )
            fc_filled += 1
        logger.info("FantasyCalc filled %d players KTC didn't rank", fc_filled)

        # Fetch matchups across the chain for the points-based views.
        chain = await client.walk_league_history(league.league_id)
        matchups: dict[tuple[str, int, int], dict] = {}
        playoff_week_start_by_league: dict[str, int] = {}
        phase_by_lwr: dict[tuple[str, int, int], str] = {}
        roster_to_user_by_league: dict[str, dict[int, str]] = {}
        league_season_by_id: dict[str, int] = {}
        league_name_by_id: dict[str, str] = {}
        display_names: dict[str, str] = {}
        for lg in chain:
            league_name_by_id[lg.league_id] = lg.name
            playoff_week_start_by_league[lg.league_id] = lg.playoff_week_start
            league_season_by_id[lg.league_id] = lg.season
            winners = await client.get_winners_bracket(lg.league_id)
            losers = await client.get_losers_bracket(lg.league_id)
            for (wk, rid), ph in classify_playoff_phases(
                winners, losers, lg.playoff_week_start, lg.playoff_round_type
            ).items():
                phase_by_lwr[(lg.league_id, wk, rid)] = ph
            rosters = await client.get_rosters(lg.league_id)
            roster_to_user_by_league[lg.league_id] = {
                r.roster_id: r.owner_id for r in rosters
            }
            users = await client.get_users(lg.league_id)
            for uid, info in users.items():
                # Most-recent display_name wins; chain order is newest-first.
                display_names.setdefault(
                    uid, info.get("team_name") or info.get("display_name") or uid
                )
            # Pull weekly matchups (cache-aware via a one-off call wrapper).
            raw_per_week: dict[int, list[dict]] = {}
            for week in range(1, 19):
                key = _MATCHUPS_CACHE_KEY.format(league_id=lg.league_id, week=week)
                raw = cache.read(key, max_age_seconds=_ONE_YEAR_SECONDS)
                if not isinstance(raw, list):
                    # Use raw HTTP (not the typed wrapper) — we want
                    # players_points, starters, etc. which the existing
                    # get_matchups helper doesn't surface.
                    resp = await client._client.get(
                        f"/league/{lg.league_id}/matchups/{week}"
                    )
                    resp.raise_for_status()
                    raw = resp.json() or []
                    cache.write(key, raw)
                raw_per_week[week] = raw
            # Assemble played matchups only — excludes Sleeper placeholder
            # entries for upcoming weeks (both teams' points == 0).
            matchups.update(
                _assemble_played_matchups(raw_per_week, lg.league_id)
            )

        # Grade every trade.
        grades_by_id: dict[str, Any] = {}
        for rt in resolved_trades:
            grade = grade_trade(
                rt,
                ktc_values=ktc_by_player_id,
                matchups=matchups,
                roster_to_user_by_league=roster_to_user_by_league,
                playoff_week_start_by_league=playoff_week_start_by_league,
                phase_by_lwr=phase_by_lwr,
                league_season_by_id=league_season_by_id,
                fmt="superflex",
                pick_values=pick_value_table,
            )
            grades_by_id[rt.trade.transaction_id] = grade

        records = aggregate_owner_records(
            list(grades_by_id.values()), display_names=display_names
        )

        # Emit the Sheets report.
        from sleeper_dynasty.output.google_sheets import GoogleSheetsReport

        report = GoogleSheetsReport(league_name=league.name, season=league.season)
        report.authenticate()
        spreadsheet_id = report.create_spreadsheet()
        report.write_definitions(spreadsheet_id)
        report.write_trade_ledger(
            spreadsheet_id,
            resolved_trades=resolved_trades,
            grades_by_trade_id=grades_by_id,
            display_names=display_names,
            league_name_by_id=league_name_by_id,
        )
        report.write_owner_standings(spreadsheet_id, records=records)
        report.set_sharing(spreadsheet_id, private=args.private)
        url = report.get_url(spreadsheet_id)
        print(f"\nTrades report ready: {url}")
    finally:
        await client.close()


async def _run_recap(args: argparse.Namespace) -> None:
    """Generate and deliver a weekly recap for one Sleeper user's league."""
    if getattr(args, "init_lore", None):
        path = _write_lore_template(Path(args.init_lore))
        print(f"Lore template written to {path}. Fill it in and pass --lore.")
        return

    cache = FileCache()
    if args.no_cache:
        cache.invalidate_all()

    client = SleeperClient()
    try:
        user_id = await client.get_user_id(args.username)
        leagues = await client.get_leagues(user_id, args.season)
        relevant = [lg for lg in leagues if lg.status in DYNASTY_LEAGUE_STATUSES]
        if not relevant:
            print(f"No dynasty-relevant leagues for {args.username}.")
            return
        league = _select_league(relevant)

        # Default week = last completed week (NFL state week - 1).
        week = args.week
        if week is None:
            state = await client.get_nfl_state()
            week = max(1, int(state.get("week", 1)) - 1)
        logger.info("Recapping %s week %d", league.name, week)

        rosters = await client.get_rosters(league.league_id)
        owner_by_roster = {r.roster_id: r.owner_name for r in rosters}
        results = await client.get_matchup_results(league.league_id, week)

        # Players (cached when possible).
        raw_players = None
        if not args.no_cache:
            cached = cache.read(_PLAYERS_CACHE_KEY)
            if isinstance(cached, dict):
                raw_players = cached
        if raw_players is None:
            raw_players = await client.get_players()
            cache.write(_PLAYERS_CACHE_KEY, raw_players)
        players = _build_players(raw_players)

        # Weekly projections for bust detection (best-effort).
        weekly_projections: dict[str, float] = {}
        try:
            raw_proj = await client.get_projections(args.season, week)
            for pid, stats in raw_proj.items():
                if isinstance(stats, dict):
                    weekly_projections[pid] = normalize_projection(
                        stats, league.scoring_settings
                    )
        except Exception as e:
            logger.warning("Weekly projections unavailable: %s", e)

        facts = build_recap_facts(
            week=week,
            league_name=league.name,
            results=results,
            rosters=rosters,
            owner_by_roster=owner_by_roster,
            players=players,
            roster_positions=league.roster_positions,
            weekly_projections=weekly_projections,
        )

        # --- Outlook (best-effort; any failure -> recap-only) ---
        outlook = None
        try:
            next_week = week + 1
            pairings = await client.get_matchup_results(
                league.league_id, next_week
            )
            # Projected team score = optimal lineup over each roster using
            # weekly projections.
            team_projected: dict[int, float] = {}
            pos_by_pid = {pid: (p.position or "") for pid, p in players.items()}
            for r in rosters:
                pmap = {
                    pid: (pos_by_pid.get(pid, ""),
                          weekly_projections.get(pid, 0.0))
                    for pid in r.players
                }
                _, total = solve_optimal_lineup(league.roster_positions, pmap)
                team_projected[r.roster_id] = total

            games = await fetch_week_schedule(args.season, next_week)
            byes = derive_byes(games)

            weather_by_home: dict[str, dict] = {}
            for g in games:
                if g.get("indoor"):
                    continue
                wx = await fetch_game_weather(g["home"], g.get("kickoff") or "")
                if wx:
                    weather_by_home[g["home"]] = wx

            weeks_remaining = max(0, (league.playoff_week_start - 1) - next_week)
            outlook = build_outlook_facts(
                week=next_week, pairings=pairings,
                owner_by_roster=owner_by_roster,
                team_projected=team_projected, rosters=rosters,
                players=players, byes=byes,
                roster_positions=league.roster_positions,
                projections=weekly_projections, games=games,
                weather_by_home=weather_by_home,
                num_playoff_teams=league.num_playoff_teams,
                weeks_remaining=weeks_remaining,
            )
        except Exception as e:
            logger.warning("Outlook unavailable (%s); recap-only", e)

        lore = None
        if args.lore:
            lore = Path(args.lore).read_text()
        persona = None
        if args.persona:
            persona = Path(args.persona).read_text()

        writer = RecapWriter(model=args.model, persona=persona)
        try:
            markdown = writer.write(facts, lore=lore, outlook=outlook)
        except anthropic.APIError as e:
            print(f"Anthropic API error: {e}", file=sys.stderr)
            return

        out_path = Path(args.out) if args.out else None
        delivery = HtmlFileDelivery(out_path=out_path)
        path = delivery.deliver(markdown, league.name, week)
        print(f"\nRecap written to {path}")
        webbrowser.open(Path(path).resolve().as_uri())
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point.

    Configures logging, dispatches to the appropriate command handler.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)

    if args.command == "analyze":
        asyncio.run(_run_analysis(args))
        return

    if args.command == "trades":
        asyncio.run(_run_trades(args))
        return

    if args.command == "recap":
        asyncio.run(_run_recap(args))
        return

    # No (or unknown) command — print help and exit non-zero.
    print("Error: a command is required (e.g. 'analyze <username>').", file=sys.stderr)
    sys.exit(1)
