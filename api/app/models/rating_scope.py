from typing import Literal

from pydantic import BaseModel, Field


class ExcludedRatingSeason(BaseModel):
    season: int
    reason: str


class ExcludedRatingRoster(BaseModel):
    roster_id: int
    reason: str


class RatingScope(BaseModel):
    status: Literal["ready", "provisional", "unavailable"]
    basis: Literal["current", "season_end"]
    label: str
    as_of: str | None = None
    reason: str | None = None
    valuation_source: Literal["stats_guy", "dynasty_process"] | None = None
    prices_as_of: str | None = None
    valuation_note: str | None = None
    included_seasons: list[int] = Field(default_factory=list)
    excluded_seasons: list[ExcludedRatingSeason] = Field(default_factory=list)
    verified_owner_count: int | None = None
    excluded_rosters: list[ExcludedRatingRoster] = Field(default_factory=list)
