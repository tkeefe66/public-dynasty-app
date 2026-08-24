# NFL Weekly Actuals — Substrate + True Drop Regret

**Date:** 2026-06-26
**Status:** Approved design, pre-implementation

## Goal

Give the engine **NFL-wide weekly fantasy points for every player** (scored to the league's settings), independent of who rostered them — and use it to make **drop regret** real: how many points a dropped player piled up *after* the owner cut him.

Today the grader only has league *matchup* actuals (roster-scoped) + projections. So the shipped `production_after_drop` can only see points a dropped player scored for *another league team* (≈nil in practice), and drop regret never fires. This builds the missing substrate.

## Non-goals (deferred — they reuse this substrate)

- **Free-agent pickup value** — value created off the waiver wire. Future project.
- **Phantom points** — re-pointing trade-story phantom at NFL actuals. Future project.
- No change to projections, the simulator, or any other metric.

## Architecture / data flow

```
Sleeper /stats/nfl/regular/{season}/{week}   (raw stats, ALL players)
  → FileCache  (per season-week, LEAGUE-AGNOSTIC, infinite TTL for completed weeks)
  → score to the league:  normalize_projection(raw_stats, league.scoring_settings)
  → lookup  { (season, week): { player_id: league_points } }
  → passed into grade_trade / build_asset_breakdown
  → drop regret: sum the lookup over the 10 NFL weeks after a dropped player's last owned week
```

Raw stats are cached **league-agnostic** (historical NFL stats never change), so the cache is a true reusable substrate across leagues and across the deferred features. League scoring is applied in-memory at grade time (cheap).

## Components (each small, single-purpose, testable)

1. **`SleeperClient.get_stats(season, week) -> list[dict]`** (`api/sleeper.py`) — mirrors `get_projections`; GET `/stats/nfl/regular/{season}/{week}`, returns the raw per-player stat list (each item: `player_id`, `stats` dict). ~5 lines.

2. **`engine/nfl_actuals.py`** (pure, no I/O):
   - `score_week(raw_stats: list[dict], scoring: dict[str, float]) -> dict[str, float]` — `{player_id: normalize_projection(item["stats"], scoring)}` for each item with a `player_id` and non-empty `stats`. Reuses `projections.normalize_projection`.
   - `next_n_weeks(start: tuple[int, int], n: int, *, weeks_per_season: int = 18) -> list[tuple[int,int]]` — the `n` (season, week) keys strictly after `start`, rolling across the season boundary (after `(Y, 18)` comes `(Y+1, 1)`). Pure list generation; callers intersect with available data.
   - `points_after_drop(pid, last_week, nfl_points, *, window=10) -> float` — `sum(nfl_points.get(wk, {}).get(pid, 0.0) for wk in next_n_weeks(last_week, window))`.

3. **Fetch/score layer** (`api/app/services/`, called from `GraderService.run` alongside the matchup fetch): determine the season-week span the chain needs, fetch+cache raw stats per week (skip already-cached completed weeks; always re-fetch the current in-progress week), build the league-scored `nfl_points` lookup, and thread it into grading.

4. **Drop-regret wiring** (`engine/trade_grader.py`): replace the dormant `_points_after_owned` (league-started, all-weeks) with a computation using the `nfl_points` lookup + `points_after_drop` over the 10-week window. `build_asset_breakdown` gains an `nfl_points` param (pure data passed in); `production_after_drop` becomes the true post-drop NFL production. Held players → the window is future/empty → 0 (unchanged behavior).

5. **Insight** (`web/components/TradeHero.tsx`): the existing dormant drop-regret generator's threshold is set to `>= 100` league points over the window; with real data it now fires on a genuine "you cut him and he balled" case. Wording: "`<owner>` dropped `<player>`, who put up `<N>` over the next 10 weeks."

## Drop-regret semantics (defaults — tunable)

- **Window:** 10 NFL weeks after `last_rostered_week`, rolling across the season boundary.
- **Points basis:** the player's NFL weekly fantasy points scored to the *league's* `scoring_settings` (not Sleeper's standard `pts_*`).
- **Threshold to surface the insight:** `>= 100` league points over the window.
- **last_rostered_week:** the latest (season, week) the player was on this owner's roster post-trade (from the existing `player_week_points`).

## Caching / fetch strategy

- **Key:** raw stats per `(season, week)`, league-agnostic, in `FileCache`. Completed weeks → effectively infinite TTL (historical). The current in-progress NFL week → short TTL / always re-fetch.
- **Span:** the chain's relevant weeks — from the earliest dropped player's window start through the current NFL week. (Cheap superset: from the earliest chain season's week 1.) First cold refresh fetches the span (one call/week; Sleeper is generous and uncapped); subsequent refreshes fetch only the current week.
- **Resilience:** a failed week fetch logs and contributes nothing (that week's points default to 0); grading never fails on a stats-fetch error, consistent with how stories/blurbs degrade.

## Scoring caveat

`normalize_projection` multiplies each raw stat by the league multiplier and sums — exact for standard scoring (pass/rush/rec yds + TDs, receptions, fumbles, etc.). Exotic positional bonuses (e.g. TE-premium `bonus_rec_te`) only apply if Sleeper emits them as keys in the player's `stats`. Implementation will diff the league's `scoring_settings` keys against a sample week's stat keys and document any unmatched keys; core scoring is accurate.

## Testing

- **`nfl_actuals` (pure):** `score_week` applies league multipliers (e.g. PPR vs non-PPR diverge); `next_n_weeks` rolls `(2024,18)`→`(2025,1)` correctly and yields exactly `n`; `points_after_drop` sums only the windowed weeks and ignores points outside it.
- **Drop regret (engine):** with an injected `nfl_points` lookup, a dropped player's `production_after_drop` equals the windowed sum; a still-held player is 0; the window stops at 10 weeks (points in week 11+ excluded).
- **Fetch/cache:** completed weeks served from cache without refetch; current week refetched; a fetch failure degrades to 0, not an exception.
- **Frontend:** the drop-regret insight renders when `production_after_drop >= 100` (vitest with crafted props).

## Rollout

`production_after_drop` already exists on the cached `AssetLine` (added dormant in the trade redesign), but cached values are the old ~0. **Bump `SCHEMA_VERSION`** so a deploy re-grades and repopulates it with true NFL-actuals values; then force-refresh per the cache-migration practice. The drop-regret insight lights up automatically once repopulated.

## Open decisions (defaults chosen; flag at spec review)

- Window length: **10** weeks. Threshold: **100** league points.
- Insight wording: "dropped X, who put up N over the next 10 weeks."
- Span superset (earliest chain season week 1) vs exact per-drop windows — default to the simpler superset; the cache makes the extra weeks ~free and serves future features.
