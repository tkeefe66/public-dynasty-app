"""Shared refresh path for both the manual /refresh route and the scheduler.

`refresh_league` is the single place that runs the grader and writes the cache,
so manual (SSE) and scheduled (background) refresh share one code path.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.services.chain_cache import ChainCache, ChainCacheEntry
from app.services.grader import GraderService
from app.services.franchise_redesign import model_for
from app.services.leaderboard import all_time_ratings, compute_season_ratings
from app.services.rating_snapshot_store import RatingSnapshotStore
from sleeper_dynasty.api.sleeper import SleeperClient

log = logging.getLogger(__name__)


async def _noop_progress(stage: str, message: str, **extra) -> None:
    return None


async def _snapshot_ratings(
    client, league_id: str, entry: ChainCacheEntry, cache_dir: Path
) -> None:
    """Persist the all-time GM ratings under the current NFL week (▲▼ trend).

    Best-effort: any failure (no get_nfl_state, network error, empty state)
    logs and is swallowed so refresh never fails on snapshotting."""
    try:
        get_state = getattr(client, "get_nfl_state", None)
        if get_state is None:
            return
        state = await get_state()
        season = state.get("season")
        week = state.get("week")
        if season is None or week is None:
            return
        week_key = f"{int(season):04d}-{int(week):02d}"
        ratings = all_time_ratings(entry)
        if not ratings:
            return
        RatingSnapshotStore(cache_dir=cache_dir).write(
            league_id, week_key, ratings, model=model_for(entry)
        )
        log.info("snapshotted GM ratings for league %s @ %s", league_id, week_key)
    except Exception:
        log.exception("rating snapshot skipped for league %s", league_id)


def month_to_date_spend(cache_dir: Path) -> float:
    """Sum of LLM cost_usd recorded so far this calendar month (UTC)."""
    from sleeper_dynasty.llm.cost_store import LlmCostStore

    now = datetime.now(tz=timezone.utc)
    prefix = f"{now.year:04d}-{now.month:02d}"
    total = 0.0
    for r in LlmCostStore(cache_dir).read_all():
        if str(r.get("ts", ""))[:7] == prefix:
            total += float(r.get("cost_usd", 0) or 0)
    return round(total, 6)


async def _effective_budget() -> float:
    """Owner-editable budget from the DB, falling back to the env default.
    Best-effort: any DB issue (e.g. table missing in a bare test env) falls
    back to the env value."""
    try:
        from app.db.engine import session_scope
        from app.repositories.app_settings import get_monthly_budget

        async with session_scope() as db:
            return await get_monthly_budget(db)
    except Exception:
        return get_settings().llm_monthly_budget_usd


async def _llm_over_budget(cache_dir: Path) -> bool:
    """True when this month's LLM spend has reached the effective budget."""
    budget = await _effective_budget()
    if not budget or budget <= 0:
        return False
    spent = month_to_date_spend(cache_dir)
    if spent >= budget:
        log.warning(
            "LLM monthly budget reached ($%.2f / $%.2f); skipping LLM generation",
            spent, budget,
        )
        return True
    return False


async def refresh_league(
    client,
    league_id: str,
    *,
    cache_dir: Path,
    force: bool = False,
    progress_cb=None,
):
    """Refresh one league: run the grader, write the ChainCache. Returns the entry.

    When the monthly LLM budget is exhausted, the grade still runs but all LLM
    prose is skipped (reusing cached stories/blurbs) — graded data stays free."""
    entry = await GraderService().run(
        client=client, current_league_id=league_id,
        progress_cb=progress_cb or _noop_progress,
        cache_dir=cache_dir, force=force,
        skip_llm=await _llm_over_budget(cache_dir),
    )
    entry.season_ratings = compute_season_ratings(entry)

    ChainCache(cache_dir=cache_dir).write(league_id, entry)
    log.info("refresh complete for %s (%d trades)",
             league_id, len(entry.resolved_trades or []))
    await _snapshot_ratings(client, league_id, entry, cache_dir)
    return entry


def known_league_ids(cache_dir: Path) -> list[str]:
    """League ids for every `chain_<id>.json` already in the cache dir."""
    out: list[str] = []
    for p in sorted(Path(cache_dir).glob("chain_*.json")):
        out.append(p.name[len("chain_"):-len(".json")])
    return out


async def refresh_all_known(
    cache_dir: Path,
    *,
    _refresh_league=refresh_league,
    _client_factory=SleeperClient,
) -> None:
    """Refresh every known league, isolating per-league failures."""
    ids = known_league_ids(cache_dir)
    if not ids:
        return
    client = _client_factory()
    try:
        for lid in ids:
            try:
                await _refresh_league(client, lid, cache_dir=cache_dir, force=False)
                log.info("auto-refresh: refreshed league %s", lid)
            except Exception:
                log.exception("auto-refresh: league %s failed", lid)
    finally:
        await client.close()


async def _member_league_ids() -> list[str]:
    """League ids with at least one member, from the identity DB."""
    from app.db.engine import session_scope
    from app.repositories import memberships

    async with session_scope() as db:
        return await memberships.league_ids_with_members(db)


async def refresh_all_members(
    cache_dir: Path,
    *,
    _refresh_league=refresh_league,
    _client_factory=SleeperClient,
    _ids_provider=_member_league_ids,
) -> None:
    """Refresh every league that has ≥1 member, isolating per-league failures.

    This is the production scheduler path: we only warm leagues someone has
    imported (not every file ever cached). ``refresh_all_known`` (glob) remains
    for tooling/tests."""
    ids = await _ids_provider()
    if not ids:
        return
    client = _client_factory()
    try:
        for lid in ids:
            try:
                await _refresh_league(client, lid, cache_dir=cache_dir, force=False)
                log.info("auto-refresh: refreshed league %s", lid)
            except Exception:
                log.exception("auto-refresh: league %s failed", lid)
    finally:
        await client.close()


async def auto_refresh_loop(
    cache_dir: Path,
    interval_seconds: int,
    *,
    _initial_delay: float = 2.0,
) -> None:
    """Background loop: re-warm member leagues almost immediately on startup (so a
    deploy / schema bump rebuilds the cache before users arrive), then every
    interval. The short delay just lets the server finish booting."""
    try:
        await asyncio.sleep(_initial_delay)
        while True:
            try:
                await refresh_all_members(cache_dir)
            except Exception:
                log.exception("auto-refresh cycle failed")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("auto-refresh loop cancelled")
        raise
