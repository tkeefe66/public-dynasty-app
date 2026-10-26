from __future__ import annotations

from pydantic import BaseModel
from typing import Literal


class OwnerRef(BaseModel):
    """Owner identity for display: handle (always present), optional team name,
    optional avatar URL."""

    user_id: str
    owner_name: str
    team_name: str | None = None
    franchise_name: str | None = None
    avatar_url: str | None = None
    membership_status: Literal["current", "former", "unverified"] = "unverified"
    last_active_season: int | None = None
