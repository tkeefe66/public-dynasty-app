from pydantic import BaseModel


class ScoringPlayer(BaseModel):
    player_id: str
    name: str
    position: str
    team: str | None = None
    rank: int
    points: float
    games: int
    points_per_game: float


class ScoringResp(BaseModel):
    league_id: str
    league_name: str
    season: int
    through_week: int
    updated_at: str
    players: list[ScoringPlayer]
