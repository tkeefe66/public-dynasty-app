"""Structured 'facts packet' models for trade stories.

Contract between the trade-story FactsBuilder (engine/trade_story.py) and the
TradeStoryWriter (llm/trade_story_writer.py). The writer serializes these to
JSON and is instructed to reference ONLY facts present here, so every number
the story cites is engine-verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sleeper_dynasty.models._signature import signature_hash


@dataclass
class PlayerArc:
    """One traded player's post-trade trajectory for the side that got them."""
    player: str
    position: str | None
    received_by: str  # user_id
    starter_weeks: int
    points_total: float
    season_high_points: float | None
    season_high_week: int | None
    season_high_is_playoff: bool
    playoff_vs_regular_pct: float | None  # +/- %; None if not enough data
    decisive_starts: int
    benched_weeks: int
    # post-trade points this player scored on ANY roster (started). Lets the
    # writer tell "flipped a stud" apart from "kept a guy who scored nothing".
    phantom_points: float = 0.0
    # True when the receiving owner never rostered this player but he played
    # elsewhere post-trade (i.e., they flipped him before he suited up). His
    # 0 starts/points here are NOT a knock on the player.
    flipped: bool = False
    # True when the owner no longer holds this player and did not flip him
    # (he was cut). flipped always wins over dropped.
    dropped: bool = False
    # Highest NFL week this player appeared on THIS owner's roster post-trade,
    # or None if he never did (e.g. drafted then cut before Week 1).
    last_rostered_week: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player": self.player, "position": self.position,
            "received_by": self.received_by, "starter_weeks": self.starter_weeks,
            "points_total": round(self.points_total, 1),
            "season_high_points": self.season_high_points,
            "season_high_week": self.season_high_week,
            "season_high_is_playoff": self.season_high_is_playoff,
            "playoff_vs_regular_pct": self.playoff_vs_regular_pct,
            "decisive_starts": self.decisive_starts,
            "benched_weeks": self.benched_weeks,
            "phantom_points": round(self.phantom_points, 1),
            "flipped": self.flipped,
            "dropped": self.dropped,
            "last_rostered_week": self.last_rostered_week,
        }


@dataclass
class PickOutcome:
    """What a traded pick became, when resolvable.

    ``became_player`` is the player the pick was drafted into and the owner
    realized directly. ``flipped_for`` is set instead when the owner flipped
    the pick *as a pick* before the draft: the pick never became its slot's
    draftee for them; they ultimately landed these player(s) through the flip.
    The two are mutually exclusive.
    """
    season: int
    round: int
    became_player: str | None
    points_per_game: float | None
    flipped_for: str | None = None
    # Realized fate of the pick: "kept" | "dropped" | "flipped" | "undrafted"
    # | None (no lineage context). "dropped" = drafted then cut.
    terminal_state: str | None = None
    # When dropped: the draftee's last rostered week for this owner, or 0 if he
    # never played a snap (drafted and cut before the season). None otherwise.
    dropped_before_week: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season, "round": self.round,
            "became_player": self.became_player,
            "flipped_for": self.flipped_for,
            "points_per_game": (round(self.points_per_game, 1)
                                if self.points_per_game is not None else None),
            "terminal_state": self.terminal_state,
            "dropped_before_week": self.dropped_before_week,
        }


@dataclass
class OwnerStrategyFacts:
    """Verified signals describing one owner's trading strategy."""
    user_id: str
    owner_name: str
    trades_count: int
    net_picks: int
    players_for_picks_count: int   # received player(s), sent pick(s) = win-now
    picks_for_players_count: int   # received pick(s), sent player(s) = rebuild
    first_round_picks_sent: int
    tilt: str  # "win-now" | "rebuild" | "balanced"
    net_ktc: float
    tendencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id, "owner_name": self.owner_name,
            "trades_count": self.trades_count, "net_picks": self.net_picks,
            "players_for_picks_count": self.players_for_picks_count,
            "picks_for_players_count": self.picks_for_players_count,
            "first_round_picks_sent": self.first_round_picks_sent,
            "tilt": self.tilt, "net_ktc": round(self.net_ktc, 0),
            "tendencies": list(self.tendencies),
        }


@dataclass
class TradeStoryFacts:
    trade_id: str
    season: int
    is_offseason: bool
    winner_user_id: str | None  # None => "even"
    lopsidedness: float          # 0..1
    margins: dict[str, float]    # ktc / production / points_started / playoff_points
    sides: list[dict[str, Any]]  # each: user_id, owner_name, player_arcs, pick_outcomes
    owners: dict[str, dict[str, Any]]  # user_id -> OwnerStrategyFacts.to_dict()
    # How the trade actually panned out by PRODUCTION (cumulative points the
    # haul scored, following the lineage chain). winner_user_id above is by trade
    # VALUE; these say who has produced more. Discrete (winner id + outcome
    # label) so they don't churn the skip-hash on weekly point drift.
    production_winner_user_id: str | None = None
    production_outcome: str | None = None  # "Lopsided." / "Won the production battle." / "Dead even." / "Too early."
    # True once at least one post-trade game has been played, so a 0 on a
    # player's arc is meaningful (benched/flipped/cut). False when the trade's
    # season has not started yet — every arc is all-zero simply because no games
    # exist, NOT because anyone "never played". Discrete (flips once) so it never
    # churns the skip-hash. is_offseason can't tell these apart (it's month-only:
    # a December post-season deal and a June pre-season deal are both offseason).
    season_underway: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id, "season": self.season,
            "is_offseason": self.is_offseason,
            "season_underway": self.season_underway,
            "winner_user_id": self.winner_user_id,
            "lopsidedness": round(self.lopsidedness, 3),
            "margins": {k: round(v, 1) for k, v in self.margins.items()},
            "sides": self.sides,
            "owners": self.owners,
            "production_winner_user_id": self.production_winner_user_id,
            "production_outcome": self.production_outcome,
        }


def facts_hash(facts: TradeStoryFacts) -> str:
    """Stable 16-char hash of a facts packet (used for incremental skip).

    Hashes a *coarsened* view so the story regenerates on material change (a
    winner flip, a flip resolving, a value crossing a band) but not on daily
    KTC / weekly-points drift. See models/_signature.py.
    """
    return signature_hash(facts.to_dict())
