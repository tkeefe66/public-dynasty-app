# Injury Context on the Production Timeline — Design (Phase 2)

**Date:** 2026-06-25
**Branch:** `worktree-injury-context` (worktree off `main`)
**Status:** Approved design, pre-implementation
**Builds on:** `docs/superpowers/specs/2026-06-24-pan-out-production-timeline-design.md` (shipped)

## Problem

The pan-out production timeline plots how a received player produced over their tenure. A
flat stretch reads as "he busted" — but a 0-point stretch caused by **injury** is a
different story, and the timeline currently can't tell them apart. We want to annotate the
timeline with injury context: **which games a received player missed to injury, broken out
by phase (Regular / Playoff / Toilet), and an estimate of the fantasy points that cost the
side.** A studded RB missing two *playoff* games hurt is a headline; a Week 4 absence is a
footnote.

## Data source (decided)

The clean nflverse *injury-report* feed (body part, Out/Questionable) **died after 2024**
(no 2025+ data, no ETA). But the signal we actually need — *did the player miss this game
due to injury* — comes from datasets that are alive and cover **2002→2025 and ongoing
2026**, for free:

- **`rosters_weekly`** (nflverse, parquet, updated daily) — per-player per-week roster
  `status`. Codes **`RES` / `PUP` / `RSN`** (injured-reserve / PUP / non-football-injury
  reserve) are a **high-confidence "missed this game to injury"** signal. Critically, this
  dataset includes **`sleeper_id` natively** — joins directly to our players, no crosswalk.
- **`snap_counts`** (nflverse, 2012→present) — a player active (`status=ACT`) but with
  **0 offensive/defensive snaps** in a week is a **softer** "didn't play" signal. Keyed by
  `pfr_player_id`; join to our players via the `ff_playerids` crosswalk (`pfr_id` →
  `sleeper_id`).
- **Sleeper `injury_status`** (already in the players dump we cache) — the **live**
  "currently Out / IR / body part" badge for in-progress injuries.

All free, no API keys, no scraping. Fetched as parquet by URL and cached to
`TRADE_GRADER_CACHE_DIR` (no beta `nflreadpy` dependency).

**Confidence tiers (made explicit in the data + UI):**
- **High** — `rosters_weekly` status in `{RES, PUP, RSN}`. Unambiguous injury absence.
- **Soft** — `status=ACT` with 0 snaps that week. Probably hurt, but could be a healthy
  scratch / coach's decision; can't be certain without the dead injury report.

**Out of scope (v1):** body-part labels and game-day Out/Questionable designations (would
need the dead feed or a paid source — a one-time Sportradar trial pull is a possible later
enhancement). The `INA` (inactive) status is treated as **soft**, not high-confidence.

## Design

### 1. Injury data layer

New module(s) to fetch + cache the nflverse parquets and expose a per-player weekly injury
map. Concretely:

- `engine/nflverse_injury.py` (pure-ish I/O wrapper): fetch `rosters_weekly_{season}.parquet`
  and `snap_counts_{season}.parquet` for the seasons in the chain, cache via the engine's
  `FileCache` (historical seasons = effectively-infinite TTL, current season = short TTL,
  matching existing caching conventions). Return a normalized
  `{(sleeper_id, season, week): InjuryWeek}` map where `InjuryWeek` carries
  `missed: bool`, `confidence: "high" | "soft"`, and `source`.
- The `pfr_id → sleeper_id` join for snap counts uses the `ff_playerids` crosswalk
  (fetched + cached once). `rosters_weekly` needs no crosswalk (`sleeper_id` native).
- **Live status:** extend the Sleeper players-dump parse to keep `injury_status`,
  `injury_start_date`, `injury_body_part` (currently dropped) for the "currently out" badge.

### 2. Missed-game detection

A **game missed to injury** for received player `pid` on owner `uid` in `(season, week)` is:
- the player was on `uid`'s roster that week (post-trade, within tenure — reuse the
  production timeline's tenure walk), AND
- there was a game in that week's **phase** (regular / playoff title-path / toilet — reuse
  `phase_by_lwr` + `playoff_week_start_by_league` from the timeline work), AND
- the player **did not play** (absent from / 0 in `players_points`), AND
- an **injury flag** applies: `rosters_weekly` status ∈ {RES,PUP,RSN} (high) or ACT+0-snap
  (soft).

The injury flag is what separates "out hurt" from a healthy benching — the whole point.
Bye weeks are naturally excluded (no game / no matchup row that week).

### 3. The metric — games missed by phase

Per received player: `games_missed = {regular, playoff, toilet}` (counts), plus the list of
missed `(season, week, confidence)` for chart markers. Playoff/Toilet reuse the existing
phase classification. This composes with the production taxonomy already in the timeline.

### 4. Points-lost estimate

Per missed game, **expected points** = the player's **trailing healthy average** of
*started Sleeper points* over their last `N` healthy games **in the current season**
(`N` ≈ 4; uses the league's real scoring via `players_points`, not nflverse's generic
fantasy points). `points_lost = expected × games_missed`, **broken out by phase**.

- **"Too early" gate:** if the player has fewer than `MIN_HEALTHY_GAMES` (≈3) healthy
  started games that season at the point of injury, **do not estimate** — surface
  `points_lost = null` / "early season — N/A" and show only the games-missed count. (No
  reaching into the prior season; "a lot changes in a year.")
- Reuses the same honest-uncertainty pattern as the production verdict's "too early".

### 5. Storage + API

- New per-player injury fields computed at **refresh** and cached on `ChainCacheEntry`
  (alongside the production payload; same try/except so an injury-stage failure never
  fails the refresh). **Bump `SCHEMA_VERSION`** (currently 8) per the cache-migration rule.
- Surfaced on the **trade-detail** response, per received player:
  `injury: { games_missed: {regular, playoff, toilet}, points_lost: {regular, playoff,
  toilet} | null, missed_weeks: [{season, week, confidence}], currently_out: bool,
  out_detail: string | null }`.
- Owner-aggregate injury roll-up is **deferred** (not in v1).

### 6. Frontend (markers + block)

In the per-trade production card (`TradeProductionCard` / `ProductionTimeline`):
- **Chart markers** on the per-player drill lines: small "out" markers at missed
  `(season, week)` points so a flat segment is visibly explained as injury, not a bust.
  High vs soft confidence rendered distinctly (e.g. solid vs hollow marker).
- **"Injury Impact" block** under the card: one line per affected received player —
  *"Bijan · missed 3 (2 reg, 1 playoff) · ~41 pts lost (est.)"* — plus a live
  *"Out since …"* detail for currently-injured players. Players with no missed games are
  omitted. When points-lost is gated, show "early season — N/A".

### 7. Edge cases

- **Crosswalk gaps:** `rosters_weekly` is `sleeper_id`-native (no gap there); only the
  snap-count soft signal depends on the `pfr_id` crosswalk — a miss there just drops the
  soft signal for that player (high-confidence IR signal still lands).
- **Soft-signal ambiguity:** 0-snap ACT weeks are labeled "soft" and visually distinct;
  never counted as high-confidence. A short game-day "Out" with the player still ACT and
  playing a few snaps is **not** caught (acceptable v1 limitation — documented).
- **Thin sample:** points-lost N/A (still show games missed).
- **Bye / eliminated weeks:** excluded (no game in phase).
- **nflverse fetch failure / offline:** injury stage logs and degrades to empty (no
  annotations), never fails the refresh.

### 8. Testing

- **Engine:** unit-test the missed-game classifier (high vs soft, phase gating, tenure
  bounds, bye exclusion) and the points-lost estimator (trailing healthy avg, too-early
  gate, per-phase split) with synthetic matchup + roster-status fixtures. The nflverse
  fetch wrapper is tested against a small saved parquet/dict fixture (no network in tests).
- **API:** injury assembly onto the trade-detail response.
- **Frontend:** markers render at missed weeks (high vs soft), Injury Impact block lines,
  N/A and currently-out states.

## Build phasing

Naturally splits so value ships early:
- **2a — substrate + detection + display:** nflverse fetch/cache, missed-game-by-phase
  detection (high + soft), markers + Injury Impact block (games missed only). No
  points-lost yet.
- **2b — points-lost estimate:** trailing-healthy-average estimator + too-early gate +
  per-phase points-lost, surfaced in the block.

Each gets its own implementation plan.

## Decided (flag if wrong)

- Free nflverse only for v1 (no Sportradar/paid, no body-part labels).
- `rosters_weekly` IR status = high confidence; snap-count-0 = soft; `INA` = soft.
- Points-lost = current-season trailing healthy average, N≈4, MIN_HEALTHY_GAMES≈3, no
  cross-season reach.
- Owner-aggregate injury roll-up deferred.
- Direct parquet fetch + `FileCache`, not the beta `nflreadpy` package.

## Open questions

- Exact `N` (trailing window) and `MIN_HEALTHY_GAMES` thresholds — sane defaults above;
  tune during implementation.
- Whether the soft (0-snap) signal is on by default in the UI or behind the high-confidence
  signal only — lean toward showing both with distinct markers.
