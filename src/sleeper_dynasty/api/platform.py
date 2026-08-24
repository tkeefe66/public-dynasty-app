"""The ingestion contract every fantasy platform implements.

One interface, two implementations (``SleeperClient``, ``YahooAdapter``) —
rather than one client plus a special case. Everything the grader needs to
read is named here; anything not on this protocol is not available to the
engine, which is what keeps a platform's encoding from leaking inward.

Three normalizations are worth calling out because they are where the two
platforms differ most:

* **Phases.** Sleeper publishes winners/losers brackets and the engine derives
  a phase map from them. Yahoo publishes no bracket resource — its scoreboard
  marks each matchup as playoff or consolation directly. So the protocol asks
  for the *phase map*, the thing both can produce, rather than for brackets,
  which only one has.
* **Transactions.** Sleeper returns one mixed feed filtered by ``type``.
  Yahoo has a typed collection. The protocol asks for trades, drops, and
  adds as three separate calls so neither caller has to know how the other
  platform slices them, and so a trade's own adds — resolved via
  ``get_trade_transactions`` — are never double-counted as waiver activity.
* **Player ids.** Every ``player_id`` crossing this boundary is a *Sleeper*
  player id, whatever the source platform calls it internally. Sleeper ID is
  the canonical key for KTC, FantasyCalc, nflverse, the chain cache, and
  lineage; translating at the boundary keeps all of them untouched.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

PLATFORM_SLEEPER = "sleeper"
PLATFORM_YAHOO = "yahoo"

# (week, roster_id) -> "playoff" | "toilet". Weeks absent from the map are
# regular season, a bye, or a placement game — see engine/playoff_phase.py.
PhaseMap = dict[tuple[int, int], str]


def platform_for_league_id(league_id: str) -> str:
    """Which platform owns ``league_id``, from the id's shape.

    Sleeper ids are all digits; Yahoo league keys are ``{game_key}.l.{id}``.
    The shapes are disjoint, so the id already stored in every membership row
    and cache filename is its own discriminator — no column, no migration, no
    second source of truth that can disagree with the id beside it.

    Raises ValueError on anything unrecognized rather than defaulting. A
    silent default would hand a Yahoo league to the Sleeper client and surface
    as a confusing 404 deep inside an HTTP call.
    """
    lid = (league_id or "").strip().lower()
    if not lid:
        raise ValueError("empty league id")
    if lid.isdigit():
        return PLATFORM_SLEEPER
    if ".l." in lid:
        return PLATFORM_YAHOO
    raise ValueError(f"unrecognized league id shape: {league_id!r}")


@runtime_checkable
class LeaguePlatform(Protocol):
    """Every read the grader performs. See the module docstring."""

    async def walk_league_history(self, league_id: str) -> list:
        """The league chain, newest season first, back to its origin."""
        ...

    async def get_rosters(self, league_id: str) -> list:
        """``Roster`` records for one league-season."""
        ...

    async def get_users(self, league_id: str) -> dict:
        """user_id -> {"display_name", "team_name", "avatar_url"}."""
        ...

    async def get_players(self) -> dict:
        """The player universe, keyed by Sleeper player_id."""
        ...

    async def get_raw_matchups(self, league_id: str, week: int) -> list[dict]:
        """Per-roster rows for one league-week.

        Each row carries ``matchup_id``, ``roster_id``, ``points``,
        ``starters``, ``players``, ``players_points`` — the shape
        ``grader_io._assemble_played_matchups`` consumes. Player ids inside
        ``starters``/``players``/``players_points`` are Sleeper ids.
        """
        ...

    async def get_phase_map(self, league) -> PhaseMap:
        """(week, roster_id) -> "playoff" | "toilet" for one league-season."""
        ...

    async def get_trade_transactions(self, league_id: str) -> list[dict]:
        """Completed trades, normalized to the Sleeper transaction shape that
        ``engine/trade_history.normalize_trade`` consumes: ``transaction_id``,
        ``roster_ids``, ``adds``, ``drops``, ``draft_picks``,
        ``waiver_budget``, ``created`` (epoch ms), ``leg`` (week)."""
        ...

    async def get_drop_transactions(self, league_id: str) -> list[dict]:
        """Non-trade transactions that dropped a player, same shape, used by
        ``engine/trade_history.build_drop_index``."""
        ...

    async def get_roster_transactions(self, league_id: str) -> list[dict]:
        """Every completed transaction that touched a roster, unfiltered by
        ``type`` or by whether it dropped anyone — same shape as
        ``get_trade_transactions``/``get_drop_transactions``.

        Exists because those two feeds are not complementary: an add that
        drops nobody (e.g. a waiver claim onto an open roster spot) matches
        neither ``type == "trade"`` nor "non-trade with a non-empty
        ``drops``" — measured at 16% of one real league's 2025 transactions.

        Supersedes a ``get_add_transactions`` that briefly existed on
        ``main``: the add and drop feeds are NOT disjoint. A waiver claim
        that adds one player and drops another satisfies both filters, and
        merging them into a replay double-applies it. Measured on the
        reference league: **204 of 356 complete non-trade transactions in
        2025 (57%) appear in both**. One unfiltered feed has no such seam.
        """
        ...

    async def get_draft_results(self, league_id: str) -> list[dict]:
        """One row per pick made: ``round``, ``pick_no``, ``draft_slot``,
        ``roster_id``, ``player_id`` (Sleeper id), ``season``."""
        ...

    async def get_traded_picks(self, league_id: str) -> list:
        """``DraftPick`` records for picks that changed hands. Platforms
        without future-pick trading return []."""
        ...

    async def get_nfl_state(self) -> dict:
        """``{"season": int, "week": int, "season_type": str}``."""
        ...

    async def get_stats(self, season: int, week: int) -> dict:
        """Raw NFL stats for one week keyed by Sleeper player_id."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        ...
