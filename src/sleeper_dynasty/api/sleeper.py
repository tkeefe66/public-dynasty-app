from __future__ import annotations

import asyncio
import logging

import httpx

from sleeper_dynasty.models.league import DraftPick, League, Matchup, MatchupResult, Roster

log = logging.getLogger(__name__)

BASE_URL = "https://api.sleeper.app/v1"
AVATAR_THUMB_BASE = "https://sleepercdn.com/avatars/thumbs"

# Sleeper settings.type -> the app's format vocabulary. This is a Sleeper
# encoding and lives with the Sleeper adapter; the engine reads League.format.
_TYPE_TO_FORMAT = {0: "redraft", 1: "keeper", 2: "dynasty"}

# Sleeper transaction types that can add or drop a player outside a trade.
_NON_TRADE_TX_TYPES = ("drop", "waiver", "free_agent")


def format_for_type(league_type) -> str:
    """Sleeper ``settings.type`` -> "dynasty" | "keeper" | "redraft".

    Anything unrecognized (``None``, an unknown int) is dynasty: an unknown
    value must never silently demote an existing league.
    """
    return _TYPE_TO_FORMAT.get(league_type, "dynasty")


def _resolve_avatar_url(u: dict) -> str | None:
    """Prefer a custom team avatar (a full URL in metadata.avatar), else the
    account avatar id rendered to a thumbnail URL, else None."""
    team_avatar = (u.get("metadata") or {}).get("avatar")
    if team_avatar:
        return team_avatar
    account_avatar = u.get("avatar")
    if account_avatar:
        return f"{AVATAR_THUMB_BASE}/{account_avatar}"
    return None


class SleeperClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        # Single-slot memo for _all_week_transactions. See its docstring.
        self._tx_cache_league_id: str | None = None
        self._tx_cache: list[dict] = []

    async def close(self) -> None:
        self._tx_cache_league_id = None
        self._tx_cache = []
        await self._client.aclose()

    async def get_user_id(self, username: str) -> str:
        resp = await self._client.get(f"/user/{username}")
        resp.raise_for_status()
        return resp.json()["user_id"]

    async def get_leagues(self, user_id: str, season: int) -> list[League]:
        resp = await self._client.get(f"/user/{user_id}/leagues/nfl/{season}")
        resp.raise_for_status()
        leagues = []
        for raw in resp.json():
            settings = raw.get("settings", {})
            leagues.append(League(
                league_id=raw["league_id"],
                name=raw["name"],
                season=int(raw["season"]),
                total_rosters=raw["total_rosters"],
                roster_positions=raw["roster_positions"],
                scoring_settings=raw.get("scoring_settings", {}),
                playoff_week_start=settings.get("playoff_week_start", 15),
                num_playoff_teams=settings.get("num_playoff_teams", 6),
                playoff_round_type=settings.get("playoff_round_type", 0),
                status=raw.get("status", "unknown"),
                format=format_for_type(settings.get("type")),
            ))
        return leagues

    async def get_rosters(self, league_id: str) -> list[Roster]:
        users_resp = await self._client.get(f"/league/{league_id}/users")
        users_resp.raise_for_status()
        user_map: dict[str, str] = {}
        for u in users_resp.json():
            name = (
                u.get("metadata", {}).get("team_name")
                or u.get("display_name", "Unknown")
            )
            user_map[u["user_id"]] = name

        rosters_resp = await self._client.get(f"/league/{league_id}/rosters")
        rosters_resp.raise_for_status()
        rosters = []
        for raw in rosters_resp.json():
            s = raw.get("settings", {})
            fpts = s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100
            fpts_against = (
                s.get("fpts_against", 0) + s.get("fpts_against_decimal", 0) / 100
            )
            rosters.append(Roster(
                roster_id=raw["roster_id"],
                owner_id=raw.get("owner_id", ""),
                owner_name=user_map.get(raw.get("owner_id", ""), "Unknown"),
                players=raw.get("players", []) or [],
                wins=s.get("wins", 0),
                losses=s.get("losses", 0),
                ties=s.get("ties", 0),
                points_for=fpts,
                points_against=fpts_against,
            ))
        return rosters

    async def get_matchups(self, league_id: str, week: int) -> list[Matchup]:
        resp = await self._client.get(f"/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        raw_list = resp.json()
        by_matchup: dict[int, list[dict]] = {}
        for entry in raw_list:
            mid = entry["matchup_id"]
            by_matchup.setdefault(mid, []).append(entry)
        matchups = []
        for mid, entries in by_matchup.items():
            if len(entries) == 2:
                matchups.append(Matchup(
                    week=week,
                    roster_id_1=entries[0]["roster_id"],
                    roster_id_2=entries[1]["roster_id"],
                    points_1=entries[0].get("points"),
                    points_2=entries[1].get("points"),
                ))
        return matchups

    async def get_matchup_results(
        self, league_id: str, week: int
    ) -> list[MatchupResult]:
        """Fetch full per-roster matchup data for one league-week.

        Unlike ``get_matchups`` (which collapses to paired team scores),
        this preserves ``starters``, ``players``, and ``players_points``
        so the recap engine can compute bench regret, heroes, and busts.
        """
        resp = await self._client.get(f"/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        results = []
        for entry in resp.json():
            results.append(MatchupResult(
                week=week,
                matchup_id=entry.get("matchup_id"),
                roster_id=entry["roster_id"],
                points=entry.get("points"),
                starters=entry.get("starters") or [],
                players=entry.get("players") or [],
                players_points=entry.get("players_points") or {},
            ))
        return results

    async def get_nfl_state(self) -> dict:
        """Fetch Sleeper's NFL state (current week, season, season_type).

        Used to default the recap to the last completed week and the
        outlook to the upcoming week.
        """
        resp = await self._client.get("/state/nfl")
        resp.raise_for_status()
        return resp.json()

    async def get_users(self, league_id: str) -> dict[str, dict[str, str | None]]:
        """Fetch league members keyed by user_id.

        Each value carries ``display_name`` (Sleeper handle), ``team_name``
        (the user-configured team name; may be None), and ``avatar_url``
        (custom team avatar or account avatar URL; may be None).
        """
        resp = await self._client.get(f"/league/{league_id}/users")
        resp.raise_for_status()
        users: dict[str, dict[str, str | None]] = {}
        for u in resp.json():
            users[u["user_id"]] = {
                "display_name": u.get("display_name") or "Unknown",
                "team_name": (u.get("metadata") or {}).get("team_name"),
                "avatar_url": _resolve_avatar_url(u),
            }
        return users

    async def get_transactions(self, league_id: str, week: int) -> list[dict]:
        """Fetch raw transactions for one league-week.

        Returns the unmodified list of transaction dicts. Caller filters by
        ``type`` (e.g., "trade") and ``status`` ("complete").
        """
        resp = await self._client.get(
            f"/league/{league_id}/transactions/{week}"
        )
        resp.raise_for_status()
        return resp.json()

    async def get_raw_matchups(self, league_id: str, week: int) -> list[dict]:
        """Per-roster matchup rows for one league-week, unmodified.

        On the protocol because ``grader_io`` needs the raw rows (starters,
        players_points) rather than the paired ``Matchup`` shape, and used to
        reach through to ``self._client`` to get them.
        """
        resp = await self._client.get(f"/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        return resp.json() or []

    async def _all_week_transactions(self, league_id: str) -> list[dict]:
        """Every transaction across the fantasy season, in week order.

        Two things this has to get right, both of which are easy to lose:

        * The 18 weeks are fetched **concurrently**, matching what the
          trade-history builder did before this moved behind the protocol.
          Serially it would be 18 round-trips per league-season — ~90 for a
          five-season chain. ``gather`` preserves input order, so week order
          is kept.
        * The result is memoized for **one** league id. Sleeper serves trades,
          drops, and adds from the same feed, so ``get_trade_transactions``,
          ``get_drop_transactions``, and ``get_roster_transactions`` would
          otherwise each walk all 18 weeks and multiply the request count.
          Callers ask for these back-to-back for the same league, so a single
          slot hits every time and keeps memory bounded — unlike a per-league
          dict on a client the scheduler shares across every league in a
          cycle.
        """
        # getattr/setattr rather than plain attribute access: tests bind this
        # method onto their own doubles (tests/helpers.wire_transaction_protocol)
        # so the real derivation runs over fake per-week data, and those doubles
        # never ran __init__.
        if getattr(self, "_tx_cache_league_id", None) == league_id:
            return self._tx_cache
        chunks = await asyncio.gather(
            *(self.get_transactions(league_id, w) for w in range(1, 19))
        )
        out: list[dict] = []
        for chunk in chunks:
            out.extend(chunk or [])
        self._tx_cache_league_id = league_id
        self._tx_cache = out
        return out

    async def get_trade_transactions(self, league_id: str) -> list[dict]:
        """Completed trades only. Already in the shape normalize_trade wants —
        Sleeper is the reference encoding for that shape."""
        return [
            tx for tx in await self._all_week_transactions(league_id)
            if tx.get("type") == "trade" and tx.get("status") == "complete"
        ]

    async def get_drop_transactions(self, league_id: str) -> list[dict]:
        """Completed non-trade transactions that dropped someone. Trade drops
        are excluded — a trade is not a drop, and build_drop_index would
        otherwise record every traded-away player as cut."""
        return [
            tx for tx in await self._all_week_transactions(league_id)
            if tx.get("type") in _NON_TRADE_TX_TYPES
            and tx.get("status") == "complete"
            and (tx.get("drops") or {})
        ]

    async def get_roster_transactions(self, league_id: str) -> list[dict]:
        """Every completed transaction that touched a roster, whatever its
        type and whatever it dropped (including nothing). Neither
        ``get_trade_transactions`` nor ``get_drop_transactions`` alone covers
        this: an add-only waiver claim drops nobody, so it fails the drops
        filter, and it isn't a trade either. Only a failed transaction never
        touched a roster, so ``status == "complete"`` is the only filter."""
        return [
            tx for tx in await self._all_week_transactions(league_id)
            if tx.get("status") == "complete"
        ]

    async def get_draft_results(self, league_id: str) -> list[dict]:
        """One row per pick made across every completed draft this season."""
        out: list[dict] = []
        for d in await self.get_drafts(league_id):
            if d.get("status") != "complete":
                continue
            season = int(d.get("season") or 0)
            for pick in await self.get_draft_picks(d["draft_id"]):
                out.append({**pick, "season": season})
        return out

    async def get_phase_map(self, league) -> dict:
        """(week, roster_id) -> "playoff" | "toilet", from the two brackets.

        Sleeper publishes brackets and the engine interprets them; Yahoo marks
        matchups directly. The protocol asks for the map both can produce.
        """
        from sleeper_dynasty.engine.playoff_phase import classify_playoff_phases
        winners = await self.get_winners_bracket(league.league_id)
        losers = await self.get_losers_bracket(league.league_id)
        return classify_playoff_phases(
            winners, losers,
            league.playoff_week_start,
            getattr(league, "playoff_round_type", 0),
        )

    async def get_drafts(self, league_id: str) -> list[dict]:
        """Fetch all drafts associated with a league.

        Returns raw draft dicts. Most leagues have one draft per season but
        startup leagues sometimes record two (startup + rookie).
        """
        resp = await self._client.get(f"/league/{league_id}/drafts")
        resp.raise_for_status()
        return resp.json()

    async def get_draft_picks(self, draft_id: str) -> list[dict]:
        """Fetch every pick made in a draft.

        Each pick dict carries ``round``, ``pick_no``, ``draft_slot``,
        ``roster_id`` (the picker), and ``player_id`` (who was selected).
        Used to resolve traded picks into the players actually drafted.
        """
        resp = await self._client.get(f"/draft/{draft_id}/picks")
        resp.raise_for_status()
        return resp.json()

    async def get_league(self, league_id: str) -> tuple[League, str | None]:
        """Fetch a single league's metadata and its previous_league_id.

        Returns (League, previous_league_id-or-None). previous_league_id
        is the linkage Sleeper uses to chain dynasty leagues across
        seasons; None on the origin season. Sleeper marks the origin
        season with the falsy sentinel string "0" rather than a JSON
        null, so that value is normalized to None here too — every
        caller (walk_league_history and any future one) gets a clean
        None without needing to know about the "0" quirk.
        """
        resp = await self._client.get(f"/league/{league_id}")
        resp.raise_for_status()
        raw = resp.json()
        settings = raw.get("settings") or {}
        league = League(
            league_id=raw["league_id"],
            name=raw["name"],
            season=int(raw["season"]),
            total_rosters=raw["total_rosters"],
            roster_positions=raw.get("roster_positions", []),
            scoring_settings=raw.get("scoring_settings", {}),
            playoff_week_start=settings.get("playoff_week_start", 15),
            num_playoff_teams=settings.get("num_playoff_teams", 6),
            playoff_round_type=settings.get("playoff_round_type", 0),
            status=raw.get("status", "unknown"),
            format=format_for_type(settings.get("type")),
        )
        prev_id = raw.get("previous_league_id")
        if not prev_id or prev_id == "0":
            prev_id = None
        return league, prev_id

    async def walk_league_history(self, league_id: str) -> list[League]:
        """Walk `previous_league_id` back to the chain origin.

        Returns leagues newest → oldest. Terminates when previous_league_id
        is null — which includes Sleeper's origin-season sentinel string
        "0", normalized to None by ``get_league``. Each step is one
        ``get_league`` call.
        """
        chain: list[League] = []
        current_id: str | None = league_id
        while current_id is not None:
            league, prev_id = await self.get_league(current_id)
            chain.append(league)
            current_id = prev_id
        return chain

    async def get_traded_picks(self, league_id: str) -> list[DraftPick]:
        resp = await self._client.get(f"/league/{league_id}/traded_picks")
        resp.raise_for_status()
        picks = []
        for raw in resp.json():
            picks.append(DraftPick(
                season=int(raw["season"]),
                round=raw["round"],
                original_owner_id=raw["previous_owner_id"],
                current_owner_id=raw["owner_id"],
            ))
        return picks

    async def get_winners_bracket(self, league_id: str) -> list[dict]:
        """Raw Sleeper winners (championship) bracket. [] on any error."""
        return await self._get_bracket(league_id, "winners_bracket")

    async def get_losers_bracket(self, league_id: str) -> list[dict]:
        """Raw Sleeper losers (toilet bowl) bracket. [] on any error."""
        return await self._get_bracket(league_id, "losers_bracket")

    async def _get_bracket(self, league_id: str, which: str) -> list[dict]:
        try:
            resp = await self._client.get(f"/league/{league_id}/{which}")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            log.warning("%s fetch failed for %s: %s", which, league_id, e)
            return []

    async def get_players(self) -> dict:
        resp = await self._client.get("/players/nfl")
        resp.raise_for_status()
        return resp.json()

    async def get_projections(
        self, season: int, week: int | None = None
    ) -> dict:
        if week:
            url = f"/projections/nfl/regular/{season}/{week}"
        else:
            url = f"/projections/nfl/regular/{season}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def get_stats(self, season: int, week: int) -> dict:
        """Raw NFL stats for ALL players in one regular-season week, keyed by player_id."""
        resp = await self._client.get(f"/stats/nfl/regular/{season}/{week}")
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}
