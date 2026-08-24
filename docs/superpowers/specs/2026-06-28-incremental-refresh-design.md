# Incremental Refresh + Cache Persistence — Design

**Date:** 2026-06-28
**Status:** Approved design, pending implementation plan
**Author:** brainstormed with Claude Code

## Problem

A league should be **built once**; subsequent opens (by the same or another user) must not trigger a total rebuild of the league's analysis data. Today they do. Two distinct, stacking causes were found:

### Problem 1 — No persistence (dominant cause)

In production (`shimmering-nature` Railway project, `ffbdynasty.com`), Postgres stores **only** users, league memberships, and app settings (`api/app/db/base.py:9-11`). The entire league analysis — `ChainCache` plus 8 other file stores (KTC snapshots, standings, ratings, raw league bundles, profiles, name overrides, engine `FileCache`, LLM cost log) — is written as **JSON files to the API container's local disk** at `/data/sleeper-dynasty/cache` (`api/Dockerfile:13` sets `TRADE_GRADER_CACHE_DIR`).

The Dockerfile and README expect a persistent volume mounted there (`README.md:248`), **but the `shimmering-nature` API service has no volume** — confirmed via `railway volume list`: the only volume in the project is `postgres-volume`, attached to Postgres. Therefore **every deploy / restart / crash wipes all analysis data**, forcing a cold `409` and full rebuild for every league. This is why it "rebuilds every time."

### Problem 2 — Cold cache triggers a full rebuild

Even with persistence fixed, a cold cache re-runs the *entire* grader pipeline (`api/app/services/grader.py::GraderService.run`, ~lines 374–1006) from scratch, re-grading frozen historical seasons that cannot change. Cold is reached via: 24h TTL expiry (`CHAIN_CACHE_TTL_SECONDS`), `SCHEMA_VERSION` bump, or the 3h auto-refresh scheduler. The full pipeline re-rolls-up immutable history on every one of these.

The pipeline already has clean incremental seams: trades key on stable Sleeper `transaction_id`s; sealed seasons + completed weeks are immutable; sealed-league raw API data is already cached at ~infinite TTL; LLM prose is already throttled + skip-hashed. Only Trade Value and GM ratings are inherently "as-of-today."

## Goals

- A built league survives deploys (persistence).
- After the first build, refreshes do **delta-only** work: grade new trades, extend new completed weeks, recompute the cheap "as-of-today" value layer — and **never re-roll-up frozen historical seasons**.
- Preserve the existing cold-start contract shape: opening a stale league still shows the SSE "refreshing…" progress, but it is now a fast incremental delta, not a full rebuild.

## Non-goals

- Migrating caches to Postgres (deferred; a volume is the chosen persistence fix). Postgres remains the future escape hatch if horizontal scaling is ever needed.
- Removing the blocking-on-open UX (rejected in favor of "block + incremental on open").
- Changing the five-metric taxonomy or any user-facing analysis semantics.

## Decisions (locked during brainstorming)

1. **Freshness model:** incremental updates only — build full once, then delta + merge.
2. **Persistence:** attach a Railway volume (fast, zero code change). Not Postgres migration.
3. **Trigger model:** block + incremental on open — keep the SSE refresh UX; make it a cheap delta.
4. **Freeze boundary:** freeze only the *expensive rollups*. The cheap "as-of-today" value layer (Trade Value swing, realized value, GM ratings, outlooks, roster ranks) is **recomputed every refresh** so it stays current.
5. **Lineage correctness boundary:** a new trade that extends an older trade's lineage triggers recompute of the affected neighbors' became/series (accepted).

---

## Phase 1 — Persistence

**Action (infra, no code):** Attach a Railway persistent volume to the `shimmering-nature` **API** service, mounted at `/data/sleeper-dynasty/cache`.

**Effects:**
- All 9 file stores survive deploys/restarts. "Build once" holds across deploys.
- The per-deploy cold `409` storm stops.

**Caveats:**
- The first deploy *after* attaching still cold-starts each league once (ephemeral data is already gone) — a one-time cost.
- A volume pins the API to a single instance (no horizontal scaling). Acceptable now; Postgres migration is the documented future path.

**Verification:** after attaching, deploy twice and confirm a league opened after deploy #1 returns `200` (cache hit) immediately after deploy #2 — no `409`, no rebuild.

---

## Phase 2 — Incremental refresh

### Architecture

`api/app/services/refresh_service.py::refresh_league` becomes **delta-aware**. It loads the prior `ChainCacheEntry`, runs a cheap **delta scan**, recomputes only what changed, **merges** into the cached blob, and writes. The full-rebuild path (`GraderService.run`) is retained and invoked only on the escape hatches below.

The unit boundaries:

- **Delta scan** — pure-ish function: `(prior_entry, freshly-walked chain + current-season transactions + latest-completed-week) -> Delta`. `Delta` enumerates: new trade IDs, new completed `(season, week)`s, the current in-progress week, and the set of lineage-affected existing trades.
- **Delta apply** — takes `prior_entry + Delta` and produces the new entry by reusing frozen sub-entries and recomputing only the delta + value layer.
- **Merge/write** — overlays per-trade sub-entries (keyed by `transaction_id`) and extends per-week structures, bumps `cached_at`, writes the blob.

### Delta scan (runs first, cheap)

1. Walk the chain (sealed leagues already cached) → current season + latest **completed** NFL week.
2. **New trades:** diff the current-season `transaction_id` set against cached `resolved_trades`. Sealed past seasons cannot produce new trades.
3. **New completed weeks:** compare cached production week-axis max `(season, week)` vs the latest-completed week.
4. **Lineage-affected set:** any cached trade whose *received* asset now appears in a new trade's `given` side (its became/series can extend).
5. **Escape hatches** → fall back to full `GraderService.run`:
   - `SCHEMA_VERSION` mismatch (cached blob shape can't be trusted).
   - `force=True` (admin "rebuild from scratch").
   - No prior entry / unreadable entry (true first build).

### What each refresh recomputes

| Layer | Behavior |
|---|---|
| **Frozen** — production tallies, standings, injury, became-grades, lineage, **LLM stories** for sealed trades / closed weeks | Reused from cache. Never recomputed. |
| **New trades** | Graded + storied + series/injury/became computed — only for them. |
| **New completed weeks** | Per-week structures (standings, ratings, production series) extended forward, not rebuilt. |
| **Current in-progress week** | Recomputed (live) — bounded to one week. |
| **Lineage-affected existing trades** | became/series recomputed from cached facts; LLM skip-hash decides whether prose regenerates. |
| **"As-of-today" value layer** — Trade Value swing, realized value, GM ratings, outlooks, roster ranks | Always recomputed (current KTC + current rosters). Compute-only — no API walks, no LLM. Cheap. |

**Why this is safe and cheap:** the expensive raw data (Sleeper matchups for sealed seasons) is already cached at infinite TTL; LLM is already throttled + skip-hashed. The redundant work today is purely **CPU re-rolling-up immutable history** — which incremental eliminates — while Trade Value (the genuinely daily-drifting metric) stays current because recomputing it is the cheap part.

### Lineage correctness boundary

A new trade can extend an older trade's "became"/timeline when an asset the older trade received is flipped onward. The delta therefore includes the **lineage-affected set** (cached trades whose received asset now appears in a new trade's `given` side). Those neighbors get became/series recomputed from cached per-(player, week) facts. **Conservative fallback** (if precise affected-set detection proves unreliable in implementation): recompute the lineage-derived layer for *all* trades, but still reuse cached per-trade production facts and LLM prose (skip-hash gates regeneration) — the expensive matchup walk stays cached either way, so even the fallback avoids the dominant cost.

### Merge / write

Take the cached entry, overlay new + recomputed per-trade sub-entries by `transaction_id`, extend per-week lists (`production_week_axis`, standings/ratings snapshots), overwrite the value layer + ratings + outlooks, bump `cached_at`, write the blob. `SCHEMA_VERSION` unchanged unless the entry shape changes.

## Error handling

- Any failure in delta apply (e.g. partial data, unexpected shape) → log and fall back to full `GraderService.run` for that league. Incremental is an optimization, never a correctness risk.
- Escape hatches (schema bump / force / no prior) bypass delta entirely.
- Surface in logs which path ran (`incremental` vs `full`) and the delta summary (N new trades, M new weeks) for observability.

## Testing

Unit tests (pure functions where possible):

1. **No-op delta:** refresh with zero new trades / zero new weeks reuses every frozen sub-entry unchanged; only the value layer + `cached_at` differ.
2. **One new trade:** adds exactly one graded entry + story + series/injury/became; recomputes only lineage-affected neighbors; all other trades' sub-entries unchanged.
3. **New completed week:** extends per-week structures forward; prior weeks' standings/ratings/series untouched.
4. **Lineage extension:** a new trade flipping a previously-received asset recomputes that older trade's became/series (and only the affected neighbors).
5. **Escape hatches:** `SCHEMA_VERSION` bump, `force=True`, and missing prior entry each take the full-rebuild path.
6. **Value layer freshness:** changing current KTC between two refreshes updates Trade Value / ratings for all trades without re-rolling-up frozen production.

## Rollout

1. Phase 1 (volume) first — independent, immediate relief, low risk.
2. Phase 2 behind the existing refresh entrypoint; full-rebuild fallback guarantees safety. Validate locally against a real league chain (incremental result == full-rebuild result for an unchanged league) before deploying.
