# Liveness: Scheduled Background Refresh — Design Spec

**Date:** 2026-06-08
**Epic:** Liveness (#4). This is Phase 1 (keep caches warm + current). New-trade *notifications* (Telegram/Discord) are a later follow-on.
**Status:** Design approved — implementation in progress.

## Problem

Data only updates when someone hits `GET /api/league/{id}/refresh`. So a trade
that drops Monday isn't reflected until the next person opens the app and
triggers a refresh, and **that** visitor waits for the whole pull + grade +
story generation. Caches go stale, and the cold-start friction lands on a real
user.

## Goal

An **in-process background scheduler** in the api that periodically refreshes
every **known** league (the ones that already have a `chain_*.json` cache file),
so caches stay warm and current with no human in the loop. Page loads stay
instant (they read the cache), and new trades appear automatically within the
schedule interval.

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Mechanism | **In-process scheduler** (a background task in the api), not an external cron worker. Railway volumes attach to one service, so the worker that writes the cache must be the api itself. |
| Which leagues | The **known** ones: every `chain_*.json` in the cache dir (leagues that have been refreshed at least once). Brand-new leagues still cold-start on first visit. |
| Frequency | Every **3 hours** by default, configurable. |
| Cost | Nearly free when nothing changed: the network pull happens, but story/became generation is incremental (`facts_hash` skip), so real work only when a trade actually appears. |
| Notifications | Out of scope this phase. |

## Architecture

- **`api/app/services/refresh_service.py` (net-new):**
  - `async refresh_league(client, league_id, *, cache_dir, force=False, progress_cb=None) -> ChainCacheEntry`
    — the shared per-league refresh: run `GraderService.run(...)` and
    `ChainCache(cache_dir).write(...)`. **The `/refresh` SSE route is refactored
    to call this**, so manual and scheduled refresh share one code path (DRY).
  - `known_league_ids(cache_dir) -> list[str]` — parse league ids from the
    `chain_*.json` filenames in the cache dir.
  - `async refresh_all_known(cache_dir) -> None` — create one `SleeperClient`,
    iterate `known_league_ids`, `refresh_league` each, **isolating errors per
    league** (one failure never stops the rest), log a one-line result per
    league, close the client.
  - `async auto_refresh_loop(cache_dir, interval_seconds) -> None` — an initial
    run after a short startup delay, then `refresh_all_known` every
    `interval_seconds`. Cycles run sequentially, so they never overlap. Cancels
    cleanly (handles `asyncio.CancelledError`).
- **`api/app/main.py`:** a FastAPI **lifespan** context manager that, when
  `settings.auto_refresh` is true, launches `auto_refresh_loop` as a background
  task on startup and cancels it on shutdown.
- **`api/app/config.py`:** add `auto_refresh: bool = True` and
  `refresh_interval_seconds: int = 10800` to `Settings` (env:
  `TRADE_GRADER_AUTO_REFRESH`, `TRADE_GRADER_REFRESH_INTERVAL_SECONDS`).
- **`api/app/routes/refresh.py`:** refactor the inline `GraderService` +
  `ChainCache.write` to call `refresh_service.refresh_league`, keeping the SSE
  progress streaming via the `progress_cb`.

## Error handling

- A league that fails to refresh logs the exception and is skipped; the loop
  continues to the next league and to the next cycle.
- The scheduler task swallows/loga any per-cycle exception so it never dies; only
  `asyncio.CancelledError` (shutdown) stops it.
- If `auto_refresh` is false, no task is started (manual `/refresh` still works).

## Testing

- `known_league_ids`: fixture cache dir with `chain_111.json`, `chain_222.json`,
  and a non-matching file → returns `["111", "222"]`.
- `refresh_all_known`: with a fake `refresh_league`, it is called once per known
  league, and a league whose refresh raises does **not** stop the others.
- The existing `/refresh` route test still passes after the refactor (the route
  delegates to `refresh_league`).
- The loop/lifespan glue is light and verified via the function tests, not an
  infinite-loop unit test.

## Docs

- `README.md`: a short "Auto-refresh (Liveness)" note (the api keeps known
  leagues warm on a schedule; manual `/refresh` still available).
- `CLAUDE.md`: a convention line (the auto-refresh scheduler + the two env vars).
- `api/.env.example`: document `TRADE_GRADER_AUTO_REFRESH` and
  `TRADE_GRADER_REFRESH_INTERVAL_SECONDS`.

## Out of scope

New-trade notifications (Telegram/Discord), multi-instance coordination (fine
for one api instance), per-league custom schedules, the Phase-2 became-grade
(parked separately).
