"""Read Yahoo leagues through the existing, Sleeper-ID-based ingestion contract.

Credentials are supplied by the caller. This adapter never persists or refreshes
tokens. Captured Yahoo fixtures cover its numeric envelopes and fragmented nodes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime

import httpx

from sleeper_dynasty.api.yahoo_json import collection, merge_fragments, unwrap
from sleeper_dynasty.models.league import League, Roster
from sleeper_dynasty.util.name_match import normalize_player_name

log = logging.getLogger(__name__)
BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"


class YahooDataError(RuntimeError):
    """Yahoo data cannot be normalized without inventing or losing information."""


class YahooAuthenticationError(RuntimeError):
    """The account needs to reconnect, or lacks permission to this resource."""


def roster_id_for(team_key) -> int:
    match = re.fullmatch(r"\d+\.l\.\d+\.t\.(\d+)", str(team_key or ""))
    if not match or int(match[1]) < 1:
        raise YahooDataError("Yahoo returned an invalid team key; retry the import.")
    return int(match[1])


def renew_to_league_key(value) -> str | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d+)_(\d+)", str(value))
    if not match:
        raise YahooDataError("Yahoo returned an invalid previous-season link.")
    return f"{match[1]}.l.{match[2]}"


def child(node, key):
    """Find a named child through only Yahoo's numeric wrapper nodes."""
    node = merge_fragments(node)
    if key in node:
        return node[key]
    for k, value in node.items():
        if str(k).isdigit():
            result = child(value, key)
            if result is not None:
                return result
    return None


def _truth(value) -> bool:
    return str(value).lower() in ("1", "true")


def _team_abbr(value):
    value = str(value or "").upper()
    return {"LA": "LAR", "JAC": "JAX", "WSH": "WAS"}.get(value, value)


def player_name_index(players):
    index = {}
    for pid, player in players.items():
        name = (
            player.get("full_name")
            or f"{player.get('first_name') or ''} {player.get('last_name') or ''}"
        )
        for position in set(
            player.get("fantasy_positions") or [player.get("position")]
        ):
            key = (normalize_player_name(name), position)
            if key[0]:
                index.setdefault(key, []).append((pid, _team_abbr(player.get("team"))))
    return index


def resolve_named_player(player, index):
    name = merge_fragments(player.get("name")).get("full")
    candidates = index.get(
        (normalize_player_name(name), player.get("display_position")), []
    )
    if len(candidates) > 1 and player.get("editorial_team_abbr"):
        team = _team_abbr(player["editorial_team_abbr"])
        candidates = [c for c in candidates if c[1] == team]
    return candidates[0][0] if len(candidates) == 1 else None


# Yahoo stat IDs are stable across NFL seasons. Compound stats expand into the
# corresponding canonical stats; actual lineup points come directly from Yahoo.
_SCORING = {
    1: ("pass_att",),
    2: ("pass_cmp",),
    3: ("pass_inc",),
    4: ("pass_yd",),
    5: ("pass_td",),
    6: ("pass_int",),
    7: ("pass_sack",),
    8: ("rush_att",),
    9: ("rush_yd",),
    10: ("rush_td",),
    11: ("rec",),
    12: ("rec_yd",),
    13: ("rec_td",),
    14: ("kr_yd", "pr_yd"),
    15: ("kr_td", "pr_td"),
    16: ("pass_2pt", "rush_2pt", "rec_2pt"),
    17: ("fum",),
    18: ("fum_lost",),
    19: ("fgm_0_19",),
    20: ("fgm_20_29",),
    21: ("fgm_30_39",),
    22: ("fgm_40_49",),
    23: ("fgm_50p",),
    24: ("fgmiss_0_19",),
    25: ("fgmiss_20_29",),
    26: ("fgmiss_30_39",),
    27: ("fgmiss_40_49",),
    28: ("fgmiss_50p",),
    29: ("xpm",),
    30: ("xpmiss",),
    32: ("sack",),
    33: ("int",),
    34: ("fum_rec",),
    35: ("def_td",),
    36: ("safe",),
    37: ("blk_kick",),
    49: ("def_st_td",),
    50: ("pts_allow_0",),
    51: ("pts_allow_1_6",),
    52: ("pts_allow_7_13",),
    53: ("pts_allow_14_20",),
    54: ("pts_allow_21_27",),
    55: ("pts_allow_28_34",),
    56: ("pts_allow_35p",),
    57: ("fum_rec_td",),
    58: ("pass_int_td",),
    70: ("yds_allow_negative",),
    71: ("yds_allow_0_99",),
    72: ("yds_allow_100_199",),
    73: ("yds_allow_200_299",),
    74: ("yds_allow_300_399",),
    75: ("yds_allow_400_499",),
    76: ("yds_allow_500p",),
    82: ("def_2pt",),
}
_POSITIONS = {
    "W/R": "WRRB_FLEX",
    "W/T": "REC_FLEX",
    "W/R/T": "FLEX",
    "Q/W/R/T": "SUPER_FLEX",
    "IR+": "IR",
}


def scoring_settings(settings: dict) -> dict[str, float]:
    result = {}
    for item in collection(child(settings.get("stat_modifiers"), "stats")):
        stat = merge_fragments(item.get("stat"))
        stat_id = int(stat["stat_id"])
        value = float(stat["value"])
        keys = _SCORING.get(stat_id)
        if not keys and value:
            raise YahooDataError(f"Yahoo scoring stat {stat_id} is not supported yet.")
        if stat.get("bonuses"):
            raise YahooDataError(
                "Yahoo scoring bonuses require explicit mapping before grading."
            )
        for key in keys or ():
            result[key] = value
    if not result:
        raise YahooDataError(
            "Yahoo returned no scoring settings; refusing an empty scoring model."
        )
    return result


class YahooAdapter:
    def __init__(
        self,
        access_token: str,
        *,
        id_map: dict[str, str] | None = None,
        max_seasons: int | None = None,
        transport=None,
    ):
        if not access_token:
            raise YahooAuthenticationError("A Yahoo access token is required.")
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30,
            headers={"Authorization": f"Bearer {access_token}"},
            transport=transport,
        )
        self._id_map = id_map
        self._name_index = {}
        self._max_seasons = max_seasons
        self._responses = {}
        self._leagues = {}
        self._metadata = {}
        self._sleeper_client = None
        self.unmapped_players: set[str] = set()
        self._limit = asyncio.Semaphore(2)
        self._id_lock = asyncio.Lock()
        self._season_owner_fallback = False

    @property
    def warnings(self):
        result = []
        if self._season_owner_fallback:
            result.append(
                "Yahoo hides manager IDs. Teams are kept separate by season; cross-season owner continuity is not verified."
            )
        if self.unmapped_players:
            result.append(
                f"{len(self.unmapped_players)} Yahoo player IDs could not be mapped; affected records are excluded."
            )
        return result

    async def close(self):
        await self._client.aclose()
        if self._sleeper_client is not None:
            await self._sleeper_client.close()

    async def _get(self, path: str, **params):
        key = (path, tuple(sorted(params.items())))
        if key in self._responses:
            return self._responses[key]
        async with self._limit:
            for attempt in range(3):
                try:
                    response = await self._client.get(
                        path, params={"format": "json", **params}
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    raise YahooDataError(
                        "Yahoo request timed out or could not connect; retry later."
                    ) from exc
                log.info("Yahoo read %s HTTP %s", path, response.status_code)
                if response.status_code in (401, 403):
                    raise YahooAuthenticationError(
                        "Yahoo refused access; reconnect and check league permissions."
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise YahooDataError(
                        "Yahoo is rate-limited or unavailable; retry the import later."
                    )
                if response.is_error:
                    raise YahooDataError(
                        f"Yahoo request failed (HTTP {response.status_code}); check league availability."
                    )
                try:
                    result = response.json()
                except ValueError as exc:
                    raise YahooDataError(
                        "Yahoo returned invalid JSON; retry later."
                    ) from exc
                if not isinstance(result, dict) or "fantasy_content" not in result:
                    raise YahooDataError(
                        "Yahoo returned an incomplete resource; retry later."
                    )
                self._responses[key] = result
                return result

    async def _ensure_ids(self):
        async with self._id_lock:
            await self._load_ids()

    async def _load_ids(self):
        if self._id_map is None:
            from sleeper_dynasty.api.yahoo_ids import fetch_yahoo_to_sleeper

            self._id_map = await fetch_yahoo_to_sleeper()
            if not self._id_map:
                self._id_map = None
                raise YahooDataError(
                    "Yahoo player-ID mapping is unavailable; retry the import later."
                )
            # The published CSV lags incoming draft classes. Resolve only
            # unique names + positions from the canonical player universe.
            self._name_index = player_name_index(await self.get_players())

    def to_sleeper_id(self, yahoo_player_id):
        return (self._id_map or {}).get(str(yahoo_player_id))

    def _player_id(self, player: dict):
        yahoo_id = str(
            player.get("player_id")
            or str(player.get("player_key", "")).rsplit(".p.", 1)[-1]
        )
        mapped = self.to_sleeper_id(yahoo_id)
        if not mapped and player.get("display_position") == "DEF":
            team = _team_abbr(player.get("editorial_team_abbr"))
            if team:
                mapped = team
        if not mapped:
            mapped = resolve_named_player(player, self._name_index)
        if mapped:
            self._id_map[yahoo_id] = mapped
            self.unmapped_players.discard(yahoo_id)
        if not mapped:
            self.unmapped_players.add(yahoo_id)
        return mapped

    async def get_league(self, league_id):
        if league_id in self._leagues:
            return self._leagues[league_id]
        payload = await self._get(f"/league/{league_id}/settings")
        meta = merge_fragments(unwrap(payload, "fantasy_content", "league"))
        if not all(meta.get(k) for k in ("league_key", "season", "num_teams")):
            raise YahooDataError(
                "Yahoo league metadata is incomplete; retry the import."
            )
        settings = merge_fragments(meta.get("settings"))
        if settings.get("scoring_type", meta.get("scoring_type")) not in (
            "head",
            "headone",
        ):
            raise YahooDataError(
                "Only Yahoo head-to-head points football leagues are supported."
            )
        slots = []
        for item in collection(settings.get("roster_positions")):
            position = merge_fragments(item.get("roster_position"))
            slot = position.get("position")
            slots.extend([_POSITIONS.get(slot, slot)] * int(position.get("count", 1)))
        league = League(
            league_id=meta["league_key"],
            name=meta.get("name") or "Yahoo league",
            season=int(meta["season"]),
            total_rosters=int(meta["num_teams"]),
            roster_positions=slots,
            scoring_settings=scoring_settings(settings),
            playoff_week_start=int(settings.get("playoff_start_week") or 0),
            num_playoff_teams=int(settings.get("num_playoff_teams") or 0),
            status="complete"
            if _truth(meta.get("is_finished"))
            else (
                "pre_draft" if meta.get("draft_status") != "postdraft" else "in_season"
            ),
            format="keeper"
            if _truth(settings.get("is_keeper_league"))
            or _truth(settings.get("uses_roster_import"))
            else "redraft",
            standings_settings={"playoff_seed_type": 0},
        )
        self._metadata[league_id] = meta
        self._leagues[league_id] = (league, renew_to_league_key(meta.get("renew")))
        return self._leagues[league_id]

    async def walk_league_history(self, league_id):
        result, seen = [], set()
        while league_id and league_id not in seen:
            seen.add(league_id)
            league, previous = await self.get_league(league_id)
            result.append(league)
            if self._max_seasons is not None and len(result) >= self._max_seasons:
                break
            league_id = previous
        return result

    async def _teams(self, league_id, suffix=""):
        data = await self._get(f"/league/{league_id}/teams{suffix}")
        node = merge_fragments(unwrap(data, "fantasy_content", "league"))
        return [merge_fragments(x["team"]) for x in collection(child(node, "teams"))]

    def _owner(self, team):
        managers = [
            merge_fragments(x.get("manager")) for x in collection(team.get("managers"))
        ]
        # Yahoo can list co-managers; manager order is authoritative and stable.
        manager = next(iter(managers), {})
        guid = str(manager.get("guid") or "")
        # Yahoo hides other managers' GUIDs as a shared placeholder. Never
        # merge different teams onto that value. Per-season team keys are the
        # honest fallback until cross-season owner mappings are supplied.
        owner = (
            guid if len(guid) >= 12 and not guid.startswith("-") else team["team_key"]
        )
        if owner == team["team_key"]:
            self._season_owner_fallback = True
        return owner, manager

    def _roster_players(self, team):
        roster = child(team, "roster")
        return [
            merge_fragments(p["player"]) for p in collection(child(roster, "players"))
        ]

    async def get_users(self, league_id):
        out = {}
        for team in await self._teams(league_id):
            owner, manager = self._owner(team)
            out[owner] = {
                "display_name": manager.get("nickname")
                or team.get("name")
                or "Unknown",
                "team_name": team.get("name"),
                "avatar_url": None,
            }
        return out

    async def get_rosters(self, league_id):
        await self._ensure_ids()
        teams = await self._teams(league_id, "/roster/players")
        payload = await self._get(f"/league/{league_id}/standings")
        node = merge_fragments(unwrap(payload, "fantasy_content", "league"))
        standings = {}
        for item in collection(child(child(node, "standings"), "teams")):
            team = merge_fragments(item["team"])
            standings[team["team_key"]] = merge_fragments(team.get("team_standings"))
        out = []
        for team in teams:
            st = standings.get(team["team_key"], {})
            totals = st.get("outcome_totals") or {}
            players = [
                p for raw in self._roster_players(team) if (p := self._player_id(raw))
            ]
            out.append(
                Roster(
                    roster_id_for(team["team_key"]),
                    self._owner(team)[0],
                    team.get("name") or "Unknown",
                    players,
                    int(totals.get("wins") or 0),
                    int(totals.get("losses") or 0),
                    int(totals.get("ties") or 0),
                    float(st.get("points_for") or 0),
                    float(st.get("points_against") or 0),
                )
            )
        return out

    async def _scoreboard(self, league_id, week):
        payload = await self._get(f"/league/{league_id}/scoreboard;week={week}")
        node = merge_fragments(unwrap(payload, "fantasy_content", "league"))
        return [
            merge_fragments(m["matchup"])
            for m in collection(child(child(node, "scoreboard"), "matchups"))
        ]

    async def _weekly_points(self, league_id, week, teams):
        # Appending /stats to the teams/roster collection silently omits stats.
        # League-scoped player collections return authoritative league scoring.
        keys = list(
            dict.fromkeys(
                p["player_key"] for t in teams for p in self._roster_players(t)
            )
        )
        totals = {}
        for start in range(0, len(keys), 25):
            batch = ",".join(keys[start : start + 25])
            data = await self._get(
                f"/league/{league_id}/players;player_keys={batch}/stats;type=week;week={week}"
            )
            node = merge_fragments(unwrap(data, "fantasy_content", "league"))
            for item in collection(child(node, "players")):
                player = merge_fragments(item["player"])
                points = merge_fragments(player.get("player_points"))
                if "total" not in points:
                    raise YahooDataError(
                        "Yahoo omitted weekly player points; retry the import."
                    )
                totals[player["player_key"]] = float(points["total"])
        if set(keys) - totals.keys():
            raise YahooDataError(
                "Yahoo omitted players from weekly scoring; retry the import."
            )
        return totals

    async def get_raw_matchups(self, league_id, week):
        league, _ = await self.get_league(league_id)
        meta = self._metadata[league_id]
        current = int(meta.get("current_week") or 0)
        if week > int(meta.get("end_week") or 18) or (
            league.status != "complete" and week >= current
        ):
            return []
        matchups = await self._scoreboard(league_id, week)
        played = [m for m in matchups if m.get("status") == "postevent"]
        if not played:
            return []
        await self._ensure_ids()
        teams = await self._teams(league_id, f"/roster;week={week}/players")
        totals = await self._weekly_points(league_id, week, teams)
        lineups = {}
        for team in teams:
            players, starters, points = [], [], {}
            for raw in self._roster_players(team):
                slot = merge_fragments(raw.get("selected_position")).get("position")
                pid = self._player_id(raw)
                if not pid:
                    if slot and slot not in ("BN", "IR", "IR+", "NA"):
                        raise YahooDataError(
                            "A Yahoo starter could not be mapped; update player identities before grading."
                        )
                    continue
                players.append(pid)
                if slot and slot not in ("BN", "IR", "IR+", "NA"):
                    starters.append(pid)
                points[pid] = totals[raw["player_key"]]
            lineups[team["team_key"]] = (players, starters, points)
        rows = []
        for idx, matchup in enumerate(played, 1):
            sides = [
                merge_fragments(t["team"]) for t in collection(child(matchup, "teams"))
            ]
            if len(sides) != 2:
                continue
            for team in sides:
                key = team["team_key"]
                if key not in lineups:
                    raise YahooDataError(
                        "Yahoo omitted a played team's weekly roster; retry the import."
                    )
                players, starters, points = lineups[key]
                rows.append(
                    {
                        "matchup_id": idx,
                        "roster_id": roster_id_for(key),
                        "points": float(
                            merge_fragments(team.get("team_points"))["total"]
                        ),
                        "players": players,
                        "starters": starters,
                        "players_points": points,
                    }
                )
        return rows

    async def get_phase_map(self, league):
        await self.get_league(league.league_id)
        meta = self._metadata[league.league_id]
        last = int(meta.get("end_week") or 18)
        if league.status != "complete":
            last = min(last, int(meta.get("current_week") or 1) - 1)
        result = {}
        if not league.playoff_week_start:
            return result
        for week in range(league.playoff_week_start, last + 1):
            for matchup in await self._scoreboard(league.league_id, week):
                if not _truth(matchup.get("is_playoffs")):
                    continue
                phase = "toilet" if _truth(matchup.get("is_consolation")) else "playoff"
                for team in collection(child(matchup, "teams")):
                    result[
                        (week, roster_id_for(merge_fragments(team["team"])["team_key"]))
                    ] = phase
        return result

    async def _transaction_week(self, league_id, timestamp):
        game = league_id.split(".l.")[0]
        data = await self._get(f"/game/{game}/game_weeks")
        game_node = merge_fragments(unwrap(data, "fantasy_content", "game"))
        date = datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()
        for item in collection(child(game_node, "game_weeks")):
            week = item.get("game_week") or item
            if week["start"] <= date <= week["end"]:
                return int(week["week"])
        return 0

    async def get_roster_transactions(self, league_id):
        await self._ensure_ids()
        # Yahoo's unfiltered collection returns the full transaction history;
        # preserving it also covers add/drop and waiver transactions atomically.
        data = await self._get(f"/league/{league_id}/transactions")
        node = merge_fragments(unwrap(data, "fantasy_content", "league"))
        out = []
        for item in collection(child(node, "transactions")):
            tx = merge_fragments(item["transaction"])
            if tx.get("status") != "successful":
                continue
            adds, drops, missing = {}, {}, False
            for item in collection(child(tx, "players")):
                player = merge_fragments(item["player"])
                pid = self._player_id(player)
                if not pid:
                    missing = True
                    continue
                for movement in collection(player.get("transaction_data")) or [
                    player.get("transaction_data")
                ]:
                    movement = merge_fragments(movement)
                    src, dest = (
                        movement.get("source_team_key"),
                        movement.get("destination_team_key"),
                    )
                    if src:
                        drops[pid] = roster_id_for(src)
                    if dest:
                        adds[pid] = roster_id_for(dest)
            if missing and tx.get("type") == "trade":
                log.warning("Yahoo trade excluded because a player could not be mapped")
                continue
            if not adds and not drops:
                continue
            timestamp = int(tx.get("timestamp") or 0)
            out.append(
                {
                    "transaction_id": tx["transaction_key"],
                    "type": tx["type"],
                    "status": "complete",
                    "adds": adds,
                    "drops": drops,
                    "roster_ids": sorted(set(adds.values()) | set(drops.values())),
                    "created": timestamp * 1000,
                    "leg": await self._transaction_week(league_id, timestamp),
                    "draft_picks": [],
                    "waiver_budget": [],
                }
            )
        return out

    async def get_trade_transactions(self, league_id):
        return [
            t
            for t in await self.get_roster_transactions(league_id)
            if t["type"] == "trade"
        ]

    async def get_drop_transactions(self, league_id):
        return [
            t
            for t in await self.get_roster_transactions(league_id)
            if t["type"] != "trade" and t["drops"]
        ]

    async def get_draft_results(self, league_id):
        await self._ensure_ids()
        data = await self._get(f"/league/{league_id}/draftresults")
        node = merge_fragments(unwrap(data, "fantasy_content", "league"))
        count = int(
            node.get("num_teams") or (await self.get_league(league_id))[0].total_rosters
        )
        picks = [
            item.get("draft_result") or item
            for item in collection(child(node, "draft_results"))
        ]
        missing = list(
            dict.fromkeys(
                p["player_key"]
                for p in picks
                if not self.to_sleeper_id(p["player_key"].rsplit(".p.", 1)[-1])
            )
        )
        for start in range(0, len(missing), 25):
            keys = ",".join(missing[start : start + 25])
            details = await self._get(f"/league/{league_id}/players;player_keys={keys}")
            players = child(
                merge_fragments(unwrap(details, "fantasy_content", "league")), "players"
            )
            for item in collection(players):
                self._player_id(merge_fragments(item["player"]))
        slots = {
            p["team_key"]: (int(p["pick"]) - 1) % count + 1
            for p in picks
            if int(p["round"]) == 1
        }
        result = []
        for pick in picks:
            pid = self._player_id(pick)
            if not pid:
                continue
            number = int(pick["pick"])
            result.append(
                {
                    "round": int(pick["round"]),
                    "pick_no": number,
                    "draft_slot": slots.get(pick["team_key"], (number - 1) % count + 1),
                    "roster_id": roster_id_for(pick["team_key"]),
                    "player_id": pid,
                    "season": int(node["season"]),
                }
            )
        return result

    async def get_drafts(self, league_id):
        league, _ = await self.get_league(league_id)
        if self._metadata[league_id].get("draft_status") != "postdraft":
            return []
        picks = await self.get_draft_results(league_id)
        return [
            {
                "draft_id": league_id,
                "league_id": league_id,
                "season": str(league.season),
                "status": "complete",
                "settings": {
                    "rounds": max((p["round"] for p in picks), default=0),
                    "teams": league.total_rosters,
                },
            }
        ]

    async def get_draft_picks(self, draft_id):
        return await self.get_draft_results(draft_id)

    async def get_traded_picks(self, league_id):
        return []

    def _sleeper(self):
        if self._sleeper_client is None:
            from sleeper_dynasty.api.sleeper import SleeperClient

            self._sleeper_client = SleeperClient()
        return self._sleeper_client

    async def get_players(self):
        return await self._sleeper().get_players()

    async def get_stats(self, season, week):
        return await self._sleeper().get_stats(season, week)

    async def get_projections(self, season):
        return await self._sleeper().get_projections(season)

    async def get_nfl_state(self):
        return await self._sleeper().get_nfl_state()
