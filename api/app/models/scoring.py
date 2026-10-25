from pydantic import BaseModel, Field


class ScoringRosterPlayer(BaseModel):
    player_id: str
    name: str
    position: str
    team: str | None = None
    rank: int | None
    tied: bool = False
    points: float | None
    games: int
    points_per_game: float | None


class ScoringPlayer(ScoringRosterPlayer):
    rank: int
    points: float
    points_per_game: float


class ScoringFranchise(BaseModel):
    roster_id: int
    owner_id: str | None
    name: str
    owner_name: str | None
    players: list[ScoringRosterPlayer]


class ScoringExcludedPlayer(BaseModel):
    player_id: str
    name: str
    position: str


class ScoringResp(BaseModel):
    league_id: str
    league_name: str
    season: int
    through_week: int
    updated_at: str
    players: list[ScoringPlayer]
    franchises: list[ScoringFranchise]
    excluded_players: list[ScoringExcludedPlayer] = Field(default_factory=list)
