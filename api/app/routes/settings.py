from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.deps import get_cache_dir
from app.services.chain_cache import ChainCache
from app.services.name_override_store import NameOverrideStore
from sleeper_dynasty.llm.cost_store import LlmCostStore
from sleeper_dynasty.llm.trade_story_writer import DEFAULT_MODEL

# League-scoped (owner-names): guarded by league membership in main.py.
league_router = APIRouter()
# Admin/global (llm-cost, config): guarded by require_admin in main.py.
admin_router = APIRouter()


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _dense_days(start: datetime, end: datetime) -> list[str]:
    """Every UTC calendar day from `start` through `end`, inclusive, as
    'YYYY-MM-DD' strings ascending. Mirrors the zero-fill convention in
    app/repositories/events.py — bucketed in pure Python, dialect-portable."""
    d = start.astimezone(timezone.utc).date()
    d_end = end.astimezone(timezone.utc).date()
    out: list[str] = []
    while d <= d_end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


class OwnerNameEntry(BaseModel):
    user_id: str
    sleeper_name: str
    display_name: str | None = None


class OwnerNamesResp(BaseModel):
    owners: list[OwnerNameEntry]


class OwnerNamesReq(BaseModel):
    overrides: dict[str, str]


def _cache_dir() -> Path:
    return get_cache_dir()


@league_router.get("/api/league/{league_id}/owner-names", response_model=OwnerNamesResp)
def get_owner_names(league_id: str) -> OwnerNamesResp:
    entry = ChainCache(cache_dir=_cache_dir()).read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    overrides = NameOverrideStore(cache_dir=_cache_dir()).read(league_id)
    owners = sorted(
        [
            OwnerNameEntry(
                user_id=uid,
                sleeper_name=(o or {}).get("owner_name") or uid,
                display_name=overrides.get(uid) or None,
            )
            for uid, o in (entry.owners or {}).items()
        ],
        key=lambda x: x.sleeper_name,
    )
    return OwnerNamesResp(owners=owners)


@league_router.put("/api/league/{league_id}/owner-names", status_code=200)
def put_owner_names(league_id: str, body: OwnerNamesReq) -> dict:
    entry = ChainCache(cache_dir=_cache_dir()).read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    cleaned = {
        k: v.strip()
        for k, v in body.overrides.items()
        if v and v.strip() and k in (entry.owners or {})
    }
    NameOverrideStore(cache_dir=_cache_dir()).write(league_id, cleaned)
    return {"ok": True}


# ── LLM cost tracking ────────────────────────────────────────────────────────


class _WriterCost(BaseModel):
    cost_usd: float
    calls: int


class _LeagueCost(BaseModel):
    cost_usd: float
    calls: int
    name: str | None = None


class _DailyBucket(BaseModel):
    date: str
    cost_usd: float
    calls: int
    by_writer: dict[str, float]


class LlmCostResponse(BaseModel):
    period: str
    total_cost_usd: float
    total_calls: int
    daily_avg_usd: float
    daily: list[_DailyBucket]
    by_writer: dict[str, _WriterCost]
    by_league: dict[str, _LeagueCost]
    active_model: str
    # Monthly-budget guardrail (independent of the selected period).
    monthly_budget_usd: float
    month_to_date_usd: float
    budget_remaining_usd: float | None  # None when no budget is configured


class ConfigResponse(BaseModel):
    llm_model: str


@admin_router.get("/api/settings/llm-cost", response_model=LlmCostResponse)
def get_llm_cost(
    period: Literal["today", "7d", "30d", "all"] = "7d",
) -> LlmCostResponse:
    store = LlmCostStore(_cache_dir())
    records = store.read_all()

    # Monthly-budget guardrail status (independent of the selected period).
    from app.services.refresh_service import month_to_date_spend
    _budget = get_settings().llm_monthly_budget_usd
    _mtd = month_to_date_spend(_cache_dir())
    _remaining = (
        round(max(0.0, _budget - _mtd), 6) if _budget and _budget > 0 else None
    )

    now = datetime.now(tz=timezone.utc)
    if period == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days = 1
    elif period == "7d":
        cutoff = now - timedelta(days=7)
        days = 7
    elif period == "30d":
        cutoff = now - timedelta(days=30)
        days = 30
    else:
        cutoff = None
        days = None

    if cutoff:
        records = [
            r for r in records
            if _parse_ts(r["ts"]) >= cutoff
        ]

    if not records:
        active = get_settings().llm_model or DEFAULT_MODEL
        return LlmCostResponse(
            period=period, total_cost_usd=0.0, total_calls=0,
            daily_avg_usd=0.0, daily=[], by_writer={}, by_league={},
            active_model=active,
            monthly_budget_usd=_budget, month_to_date_usd=_mtd,
            budget_remaining_usd=_remaining,
        )

    total_cost = round(sum(r["cost_usd"] for r in records), 6)
    total_calls = len(records)

    if days is None:
        first_ts = _parse_ts(records[0]["ts"])
        days = max(1, (now - first_ts).days + 1)
        window_start = first_ts
    else:
        window_start = cutoff

    # by_writer aggregation
    writer_map: dict[str, _WriterCost] = {}
    for r in records:
        w = r["writer"]
        if w not in writer_map:
            writer_map[w] = _WriterCost(cost_usd=0.0, calls=0)
        writer_map[w].cost_usd = round(writer_map[w].cost_usd + r["cost_usd"], 6)
        writer_map[w].calls += 1

    # daily buckets
    bucket_map: dict[str, dict] = {}
    for r in records:
        date_key = r["ts"][:10]
        if date_key not in bucket_map:
            bucket_map[date_key] = {
                "date": date_key, "cost_usd": 0.0, "calls": 0, "by_writer": {},
            }
        b = bucket_map[date_key]
        b["cost_usd"] = round(b["cost_usd"] + r["cost_usd"], 6)
        b["calls"] += 1
        w = r["writer"]
        b["by_writer"][w] = round(b["by_writer"].get(w, 0.0) + r["cost_usd"], 6)

    # Zero-fill quiet days so the stacked chart's x-axis is dense — otherwise
    # a handful of active days silently stretches to fill the whole window.
    for day in _dense_days(window_start, now):
        if day not in bucket_map:
            bucket_map[day] = {"date": day, "cost_usd": 0.0, "calls": 0, "by_writer": {}}

    daily = [
        _DailyBucket(**b)
        for b in sorted(bucket_map.values(), key=lambda x: x["date"])
    ]

    # by_league aggregation (names resolved best-effort from the chain cache).
    league_map: dict[str, _LeagueCost] = {}
    for r in records:
        lid = r.get("league_id") or "?"
        lc = league_map.get(lid)
        if lc is None:
            lc = _LeagueCost(cost_usd=0.0, calls=0)
            league_map[lid] = lc
        lc.cost_usd = round(lc.cost_usd + r["cost_usd"], 6)
        lc.calls += 1
    _cache = ChainCache(cache_dir=_cache_dir())
    for lid, lc in league_map.items():
        entry = _cache.read(lid)
        if entry is not None:
            lc.name = (entry.league_name_by_id or {}).get(lid)

    active = get_settings().llm_model or DEFAULT_MODEL

    return LlmCostResponse(
        period=period,
        total_cost_usd=total_cost,
        total_calls=total_calls,
        daily_avg_usd=round(total_cost / days, 6),
        daily=daily,
        by_writer=writer_map,
        by_league=league_map,
        active_model=active,
        monthly_budget_usd=_budget,
        month_to_date_usd=_mtd,
        budget_remaining_usd=_remaining,
    )


@admin_router.get("/api/settings/config", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    return ConfigResponse(llm_model=get_settings().llm_model or DEFAULT_MODEL)
