from typing import Literal

from pydantic import BaseModel


class RatingScope(BaseModel):
    status: Literal["ready", "unavailable"]
    basis: Literal["current", "season_end"]
    label: str
    as_of: str | None = None
    reason: str | None = None
