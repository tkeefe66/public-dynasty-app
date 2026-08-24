"""Side-bets ledger: manually recorded 1-vs-1 money bets between owners.
League-gated at include time (league_guard in main.py); handlers that write
also inject get_current_user for the audit trail. DB-backed — these routes
never 409 on a cold chain cache; owner names degrade to raw user_ids."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.models import SideBet, User
from app.db.session import get_db
from app.deps import get_cache_dir
from app.models.bets import (
    BetsSummaryResp,
    OwnerBetSummary,
    SideBetCreate,
    SideBetListResp,
    SideBetUpdate,
    SideBetView,
)
from app.models.common import OwnerRef
from app.repositories import side_bets as side_bets_repo
from app.services import side_bets as service
from app.services.chain_cache import ChainCache
from app.services.identity import apply_name_overrides, owner_ref
from app.services.name_override_store import NameOverrideStore

router = APIRouter()

_FIELD_EDITS = (
    "description",
    "amount_cents",
    "season",
    "side_a_owner_id",
    "side_b_owner_id",
    "made_at",
)


def _resolver(league_id: str):
    """Owner-name lookup with graceful cold-cache degradation."""
    cache_dir = get_cache_dir()
    entry = ChainCache(cache_dir=cache_dir).read(league_id)
    if entry is not None:
        overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
        if overrides:
            apply_name_overrides(entry, overrides)

    def ref(uid: str) -> OwnerRef:
        if entry is None:
            return OwnerRef(user_id=uid, owner_name=uid)
        return owner_ref(entry, uid)

    return ref


def _view(bet: SideBet, ref) -> SideBetView:
    return SideBetView(
        id=bet.id,
        season=bet.season,
        description=bet.description,
        amount_cents=bet.amount_cents,
        side_a=ref(bet.side_a_owner_id),
        side_b=ref(bet.side_b_owner_id),
        status=bet.status,
        winner_owner_id=bet.winner_owner_id,
        made_at=bet.made_at,
        settled_at=bet.settled_at,
    )


@router.post(
    "/api/league/{league_id}/bets", response_model=SideBetView, status_code=201
)
async def create_bet(
    league_id: str,
    body: SideBetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SideBetView:
    try:
        service.validate_bet_fields(
            side_a_owner_id=body.side_a_owner_id,
            side_b_owner_id=body.side_b_owner_id,
            amount_cents=body.amount_cents,
            description=body.description,
        )
    except service.BetValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    bet = SideBet(
        league_id=league_id,
        season=body.season,
        description=body.description.strip(),
        amount_cents=body.amount_cents,
        side_a_owner_id=body.side_a_owner_id,
        side_b_owner_id=body.side_b_owner_id,
        made_at=body.made_at,
        created_by_user_id=user.id,
    )
    await side_bets_repo.create(db, bet)
    return _view(bet, _resolver(league_id))


@router.get("/api/league/{league_id}/bets", response_model=SideBetListResp)
async def list_bets(
    league_id: str,
    owner_id: str | None = Query(None),
    season: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> SideBetListResp:
    bets = await side_bets_repo.list_for_league(
        db, league_id, owner_id=owner_id, season=season
    )
    ref = _resolver(league_id)
    return SideBetListResp(bets=[_view(b, ref) for b in bets])


@router.get("/api/league/{league_id}/bets/summary", response_model=BetsSummaryResp)
async def bets_summary(
    league_id: str,
    season: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> BetsSummaryResp:
    bets = await side_bets_repo.list_for_league(db, league_id, season=season)
    totals = service.summarize(bets)
    ref = _resolver(league_id)
    ranked = sorted(totals.values(), key=lambda t: t.net_cents, reverse=True)
    return BetsSummaryResp(
        owners=[
            OwnerBetSummary(
                owner=ref(t.owner_id),
                won=t.won,
                lost=t.lost,
                pushed=t.pushed,
                cents_won=t.cents_won,
                cents_lost=t.cents_lost,
                net_cents=t.net_cents,
                cents_at_stake=t.cents_at_stake,
                biggest_win_cents=t.biggest_win_cents,
                worst_loss_cents=t.worst_loss_cents,
            )
            for t in ranked
        ]
    )


@router.patch("/api/league/{league_id}/bets/{bet_id}", response_model=SideBetView)
async def update_bet(
    league_id: str,
    bet_id: str,
    body: SideBetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SideBetView:
    bet = await side_bets_repo.get(db, league_id, bet_id)
    if bet is None:
        raise HTTPException(status_code=404, detail="bet not found")

    edits = body.model_dump(exclude_unset=True)
    if "winner_owner_id" in edits and "status" not in edits:
        raise HTTPException(
            status_code=422, detail="winner can only change with a status change"
        )
    field_edits = {k: v for k, v in edits.items() if k in _FIELD_EDITS}
    if field_edits and bet.status != service.OPEN:
        raise HTTPException(
            status_code=422,
            detail="only open bets can be edited — revert to open first",
        )

    try:
        for key, value in field_edits.items():
            setattr(bet, key, value)
        service.validate_bet_fields(
            side_a_owner_id=bet.side_a_owner_id,
            side_b_owner_id=bet.side_b_owner_id,
            amount_cents=bet.amount_cents,
            description=bet.description,
        )
        if "status" in edits:
            new_status = edits["status"]
            winner = edits.get("winner_owner_id")
            service.validate_status(
                status=new_status,
                winner_owner_id=winner,
                side_a_owner_id=bet.side_a_owner_id,
                side_b_owner_id=bet.side_b_owner_id,
            )
            bet.status = new_status
            bet.winner_owner_id = winner
            if new_status == service.OPEN:
                bet.settled_at = None
                bet.settled_by_user_id = None
            else:
                bet.settled_at = edits.get("settled_at") or date.today()
                bet.settled_by_user_id = user.id
    except service.BetValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await db.flush()
    return _view(bet, _resolver(league_id))
