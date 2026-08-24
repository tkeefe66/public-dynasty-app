from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class League:
    league_id: str
    name: str
    season: int
    total_rosters: int
    roster_positions: list[str]
    scoring_settings: dict[str, float]
    playoff_week_start: int
    num_playoff_teams: int
    status: str  # "pre_draft", "drafting", "in_season", "complete"
    playoff_round_type: int = 0
    # "dynasty" | "keeper" | "redraft". Platform-neutral by design: each
    # adapter maps its own native representation (Sleeper's settings.type
    # int, Yahoo's keeper settings) onto this vocabulary, so the engine never
    # learns a platform's encoding. Defaults to dynasty — this app was
    # dynasty-only until recently and an adapter that omits it must never
    # silently demote a league.
    format: str = "dynasty"


@dataclass
class Roster:
    roster_id: int
    owner_id: str
    owner_name: str
    players: list[str]
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float


@dataclass
class Matchup:
    week: int
    roster_id_1: int
    roster_id_2: int
    points_1: float | None
    points_2: float | None


@dataclass
class DraftPick:
    season: int
    round: int
    original_owner_id: int
    current_owner_id: int


@dataclass
class MatchupResult:
    """Full per-roster result for one league-week, including per-player
    points and the actually-started lineup. Two MatchupResults sharing a
    ``matchup_id`` are opponents.
    """
    week: int
    matchup_id: int | None
    roster_id: int
    points: float | None
    starters: list[str]
    players: list[str]
    players_points: dict[str, float]
