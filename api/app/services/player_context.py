"""Collect shared NFL news during refresh and enrich an edition without extra LLM calls."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.services.player_context_store import PlayerContextStore
from sleeper_dynasty.api.player_context import PlayerContextClient, SourceUnavailable, normalize_news
from sleeper_dynasty.engine.player_context import build_context

log = logging.getLogger(__name__)
SUCCESS_TTL = 6 * 3600


async def collect_player_news(client, league_id, cache_dir, *, now=None, source=None, clock=None):
    """Free collection runs even when all recaps exist or model spend is gated."""
    clock = clock or (lambda value=now: value or datetime.now(timezone.utc))
    now = clock()
    store = PlayerContextStore(cache_dir)
    try:
        async with asyncio.timeout(45):
            with store.claim() as claimed:
                if not claimed:
                    return
                provider = store.read("news-provider") or {}
                if provider.get("retry_at", 0) > now.timestamp():
                    return
                state = await client.get_nfl_state()
                if state.get("season_type") != "regular":
                    return
                season = int(state["season"])
                rosters = await client.get_rosters(league_id)
                ids = sorted({p for roster in rosters for p in roster.players if p and p != "0"})
                due = [p for p in ids if (store.read(f"news:{season}:{p}") or {}).get("retry_at", 0) <= now.timestamp()]
                if not due:
                    return
                async with httpx.AsyncClient() as http:
                    active = source or PlayerContextClient(http)
                    for offset in range(0, len(due), 10):
                        batch = due[offset:offset + 10]
                        fetched = await active.news(batch)
                        received_at = clock()
                        for pid in batch:
                            key = f"news:{season}:{pid}"
                            previous = store.read(key) or {}
                            # setdefault retains the first time each exact version
                            # was observed, across restarts and subsequent leagues.
                            observations = {n["id"]: n for n in previous.get("items", [])}
                            for item in normalize_news(fetched[pid], observed_at=received_at):
                                observations.setdefault(item["id"], item)
                            store.write(key, {"items": list(observations.values()), "fetched_at": received_at.isoformat(),
                                              "retry_at": received_at.timestamp() + SUCCESS_TTL})
                        log.info("Player news collected season=%s players=%s", season, len(batch))
                store.write("news-provider", {"retry_at": 0, "error": None})
    except Exception as exc:
        delay = exc.retry_after if isinstance(exc, SourceUnavailable) else 900
        log.warning("Player news collection failed (%s); cached evidence retained; retry after %.0fs", type(exc).__name__, delay)
        try:
            store.write("news-provider", {"retry_at": clock().timestamp() + delay,
                                           "error": str(exc) if isinstance(exc, SourceUnavailable) else type(exc).__name__})
        except OSError:
            log.warning("Could not persist player-news backoff", exc_info=True)


async def load_player_context(cache_dir, season, week, results, players, *, now=None, source=None, clock=None):
    clock = clock or (lambda value=now: value or datetime.now(timezone.utc))
    now = clock()
    store = PlayerContextStore(cache_dir)
    resources = {}
    failures = []
    async with httpx.AsyncClient() as http:
        active = source or PlayerContextClient(http)
        for resource in ("snaps", "ids", "schedule"):
            key = f"{resource}:{season}"
            # Refreshes for different leagues share source data and backoff.
            # Never let a late failure overwrite another collector's success.
            with store.claim(key) as claimed:
                cached = store.read(key) or {}
                if cached.get("retry_at", 0) <= clock().timestamp():
                    if claimed:
                        try:
                            rows = await active.csv_rows(resource, season)
                            received_at = clock()
                            cached = {"rows": rows, "fetched_at": received_at.isoformat(),
                                      "retry_at": received_at.timestamp() + SUCCESS_TTL}
                        except Exception as exc:
                            delay = exc.retry_after if isinstance(exc, SourceUnavailable) else 900
                            cached = {**cached, "error": f"{resource} unavailable", "retry_at": clock().timestamp() + delay}
                            log.warning("Player context %s unavailable (%s); retry after backoff", resource, type(exc).__name__)
                        store.write(key, cached)
                    else:
                        failures.append(f"{resource} refresh in progress; only cached evidence could be used")
            if cached.get("error"):
                failures.append(cached["error"])
            resources[resource] = cached.get("rows", [])
    ids = {p for r in results for p in r.players}
    news = {pid: (store.read(f"news:{season}:{pid}") or {}).get("items", []) for pid in ids}
    packet = build_context(season=season, week=week, now=now, results=results, players=players, news_by_player=news,
                           snap_rows=resources["snaps"], id_rows=resources["ids"], schedule_rows=resources["schedule"])
    provider = store.read("news-provider") or {}
    if provider.get("error") and provider.get("retry_at", 0) > now.timestamp():
        failures.append("Player news refresh unavailable; only previously collected reports could be used")
    if failures:
        packet["note"] = " ".join(filter(None, [packet["note"], "; ".join(failures) + "."]))
    return packet
