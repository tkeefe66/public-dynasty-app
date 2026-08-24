"""Response/request shapes for the side-bets ledger."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.models.common import OwnerRef


class SideBetCreate(BaseModel):
    description: str
    amount_cents: int
    season: int
    side_a_owner_id: str
    side_b_owner_id: str
    made_at: date


class SideBetUpdate(BaseModel):
    """PATCH body. Field edits only apply to open bets; winner_owner_id is
    only accepted alongside a status change."""

    description: str | None = None
    amount_cents: int | None = None
    season: int | None = None
    side_a_owner_id: str | None = None
    side_b_owner_id: str | None = None
    made_at: date | None = None
    status: Literal["open", "settled", "push", "void"] | None = None
    winner_owner_id: str | None = None
    settled_at: date | None = None


class SideBetView(BaseModel):
    id: str
    season: int
    description: str
    amount_cents: int
    side_a: OwnerRef
    side_b: OwnerRef
    status: str
    winner_owner_id: str | None = None
    made_at: date
    settled_at: date | None = None


class SideBetListResp(BaseModel):
    bets: list[SideBetView]


class OwnerBetSummary(BaseModel):
    owner: OwnerRef
    won: int
    lost: int
    pushed: int
    cents_won: int
    cents_lost: int
    net_cents: int
    cents_at_stake: int
    biggest_win_cents: int
    worst_loss_cents: int


class BetsSummaryResp(BaseModel):
    owners: list[OwnerBetSummary]
