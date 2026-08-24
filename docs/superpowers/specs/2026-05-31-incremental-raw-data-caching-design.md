# Incremental Raw-Data Caching — Design

**Date:** 2026-05-31
**Status:** Approved, ready for implementation plan
**Scope:** Phase 2 of a two-phase effort. Phase 1 (provenance-aware pick grading)
shipped on `main`. This phase makes the API refresh stop re-pulling sealed
historical seasons. Builds on the resolution semantics pinned by
`2026-05-30-provenance-aware-pick-grading-design.md`.

## Problem

Every API refresh re-fetches and re-grades the **entire** league chain from
scratch. `GraderService.run` walks back to league origin and, for each season,
makes ~40 Sleeper API calls (`api/app/services/grader.py`,
`src/sleeper_dynasty/engine/trade_history.py`,
`api/app/services/grader_io.py`):

- **trade history per league:** `get_users`, `get_rosters`, **18×**
  `get_transactions`, `get_drafts`, `get_draft_picks` (~21 calls).
- **supporting data per league:** `get_rosters`, `get_users`, **18×** matchups
  (~20 calls).

For an N-season chain that is ~40·N calls per refresh, even though only the
current season can have changed. The `ChainCache` output blob has a 24h TTL but
no per-season reuse, and nothing checks for immutable data before rebuilding.

## The constraint that forces the design

Phase 1 established that **production and impact are cumulative**: a trade from a
sealed past season keeps changing its grade as the players involved keep scoring
in the **current** season. Therefore the **graded output of a sealed season is
NOT immutable** and cannot be cached.

What *is* immutable once a league has `status == "complete"` is its **raw fetched
data** — transactions, drafts, draft picks, rosters, users, and played-week
matchups. That raw fetching is exactly the expensive part.

**Boundary (forced):** cache the raw fetch bundle per sealed league; re-fetch
only the current (incomplete) league; **re-grade all trades in memory every
refresh**. Grading is cheap CPU; cumulative production needs the latest
current-season matchups even for old trades.

Cross-season pick resolution stays correct *for free*: we cache **raw** data, not
resolved trades, so resolution re-runs each refresh over the full assembled set
(a 2023-traded pick still resolves once the cached 2024 draft data is present).

This is rejected explicitly: caching final per-season **grades** (would go stale
as current-season games are played) and caching KTC/FantasyCalc values (the
snapshot lens is defined as *today's* market value and must stay fresh).

## Architecture

A new `LeagueRawCache` sits **beneath** `GraderService.run`. The output
`ChainCacheEntry` blob and the `409` cold-start + SSE refresh contract are
**unchanged** — Phase 2 only accelerates the rebuild that populates them.

```
GraderService.run
  walk chain (League list, newest->oldest)
  construct LeagueRawCache(cache_dir, force=<from refresh route>)
  build_trade_history(client, ..., league_cache)      # per-league trade bundle
  pull_supporting_data(client, chain, ..., league_cache, players)  # matchup bundle
  grade ALL trades in memory                            # unchanged
  write ChainCache output blob                          # unchanged
```

Per league, the cache decision is identical in both consumers:

```
if league.status == "complete":
    hit = league_cache.read_<bundle>(league.league_id)   # unless force
    if hit is not None: use hit
    else: fetch live, then league_cache.write_<bundle>(league.league_id, bundle)
else:
    fetch live (never cached — current/incomplete season)
```

A league is only ever **written** to the cache when sealed, so the current
season is never served stale, and a season that *just* completed is fetched
fresh on the first refresh that observes the seal, then cached thereafter.

## Components

### 1. `LeagueRawCache` — *new, `api/app/services/league_raw_cache.py`*

- One JSON file per league: `raw_{league_id}.json` under `TRADE_GRADER_CACHE_DIR`
  (the same mounted volume as `ChainCache`).
- Holds two independently-readable bundles plus a version tag:
  ```json
  {
    "schema_version": 1,
    "league_id": "...",
    "trade_bundle": { ... },
    "matchup_bundle": { ... }
  }
  ```
- **Effectively-infinite TTL** for sealed data; a `SCHEMA_VERSION` mismatch on
  read → treat as a miss (re-fetch + overwrite). This guards against silently
  reading an incompatible old bundle after a format change.
- `force=True` (constructor flag) makes all reads return `None` (bypass), while
  writes still occur — so a forced refresh re-pulls and refreshes the cache.
- **Serialization gotchas** (mirrors `ChainCache`'s existing handling):
  - matchups are keyed by the tuple `(league_id, week, roster_id)`; persist as a
    list of `{league_id, week, roster_id, entry}` records and rebuild the dict on
    read.
  - `roster_to_user` has `int` roster_id keys; JSON stringifies them — coerce
    back to `int` on read.
- Interface (one read/write pair per bundle so the two consumers stay decoupled):
  `read_trade_bundle(league_id)`, `write_trade_bundle(league_id, bundle)`,
  `read_matchup_bundle(league_id)`, `write_matchup_bundle(league_id, bundle)`.
  Reads/writes of one bundle must preserve the other already on disk (read existing
  file, merge, write) so writing the matchup bundle doesn't clobber the trade
  bundle and vice-versa.

### 2. Trade-history fetch — *modified `src/sleeper_dynasty/engine/trade_history.py`*

- `build_trade_history` and `_fetch_league_season_data` gain an **optional**
  `league_cache=None` parameter. The trade bundle is exactly the existing
  `_fetch_league_season_data` return **minus** the `League` object (the `League`
  comes from the chain walk and is re-attached after load):
  `{users, roster_to_user, raw_trades, drafts, draft_picks_by_draft_id}`.
- Gating per the Architecture pseudocode, keyed on `league.status`. `None`
  cache (the CLI path) ⇒ always fetch live, exactly as today.

### 3. Supporting-data fetch — *modified `api/app/services/grader_io.py`*

- `pull_supporting_data` gains the same optional `league_cache=None`. Its
  per-league loop caches a **matchup bundle**:
  `{matchups_for_league, playoff_week_start, roster_to_user, league_name, season,
  users_display_names}`. Same `status == "complete"` gating.
- `pull_supporting_data` also gains a `players` parameter (see §4) to avoid the
  redundant `get_players()` call.

### 4. `get_players()` de-duplication — *modified `grader.py` + `grader_io.py`*

`GraderService.run` already calls `client.get_players()` once (for
`player_names`); `pull_supporting_data` calls it again. Pass the already-fetched
players blob into `pull_supporting_data` and drop its second call. This removes a
large payload fetch from **every** refresh, including warm ones.

### 5. Force escape hatch — *modified `api/app/routes/refresh.py`*

The refresh route accepts an optional `force` query param (`?force=1`). When set,
`GraderService.run` builds the `LeagueRawCache` with `force=True`, bypassing reads
(but still writing). For operator use when Sleeper corrects historical data —
re-pull without a redeploy or a full cache wipe. Low priority; may be deferred if
the plan gets tight, leaving `SCHEMA_VERSION` bump / cache-dir clear as the
fallback.

## Data flow

- **Cold** (no raw cache): identical to today — fetch everything, grade, write
  `ChainCache`; additionally write `raw_{league_id}.json` for each **sealed**
  league encountered.
- **Warm:** walk chain; sealed leagues' bundles load from disk; only the current
  league hits the network (~40 calls vs ~40·N), plus one `get_players()` blob;
  assemble → resolve picks → grade all → write `ChainCache`.

## Correctness invariants

1. **Warm output == cold output.** For the same upstream data, a run served from
   the raw cache must produce identical `grades` and `resolved_trades` to a run
   that fetched everything live. Caching raw data must not change results. This is
   the headline test.
2. **Cross-season resolution preserved** — resolution recomputes each refresh over
   the full assembled raw set.
3. **No stale-before-seal window** — a league is cached only once `status ==
   "complete"`; the current season is always live.

## Edge cases

- **Just-completed league:** fetched fresh on the first sealed-observing refresh,
  cached after. Handled by write-only-when-sealed.
- **Sleeper corrects sealed data:** sticks under infinite TTL; resolved via
  `?force=1` or `SCHEMA_VERSION` bump / cache-dir clear.
- **Format change:** old bundles fail the `SCHEMA_VERSION` check ⇒ re-fetched.
- **Partial file / one bundle missing:** a missing/unreadable bundle is a miss for
  that bundle only ⇒ that fetch runs live; the present bundle is still used.
- **CLI unaffected:** `league_cache=None`; the CLI already caches individual
  Sleeper calls via `FileCache`. Out of scope here.

## Testing

- `LeagueRawCache` round-trip: tuple-keyed matchups and int-keyed rosters
  serialize and restore exactly; writing one bundle preserves the other.
- **Sealed league served from cache:** a `status=="complete"` league with a cached
  bundle does **not** hit the Sleeper client (assert the client/fetch is not
  called for it).
- **Current league always fetched:** an incomplete league is fetched even when a
  (stale) file exists, and is **not** written.
- **Newly-sealed league is stored:** first run with `status=="complete"` writes
  the bundle.
- **`force=True`** bypasses reads but still writes.
- **`SCHEMA_VERSION` mismatch** ⇒ treated as a miss.
- **Cold == warm equivalence** end-to-end through `GraderService.run` with a
  fake client: assert identical `ChainCacheEntry.grades` / `resolved_trades`
  between a cold run and a subsequent warm run.
- Follow `superpowers:test-driven-development`.

## Out of scope

- Caching graded output, KTC, or FantasyCalc (must stay fresh).
- Changing the `ChainCache` blob shape, its 24h TTL, or the 409/SSE contract.
- CLI caching (already handled by `FileCache`).
- Per-week incremental matchup fetching within the current season (the current
  league is fetched whole; a finer in-season delta is a possible future phase).
