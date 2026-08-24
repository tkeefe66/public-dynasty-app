# Pan-Out Production Timeline — Design

**Date:** 2026-06-24
**Branch:** `feat/pan-out-redesign`
**Status:** Approved design, pre-implementation

## Problem

The per-trade "DID IT PAN OUT?" card (`web/components/TradeValueProgress.tsx`) and the
owner-aggregate "DID YOUR TRADES PAN OUT?" card
(`web/components/ownerdeepdive/ValueProgressionCard.tsx`) both plot **KTC value over
time**. KTC value history only exists from ~May 2026 forward (see the
`asset-value-career-arc` memory). For any trade older than that — i.e. most trades — the
chart has only ~3 recent weekly snapshots to plot. The result, visible in production:

- Lines are **visually flat** — ~3 data points spanning ~3 weeks can't show whether a
  multi-year-old trade panned out.
- Deltas are **tiny on a huge scale** (`+7` / `−107` against a `9,999` line are invisible).
- The verdict reads **"Boring. Neither side has moved much yet"** — technically the
  `<5%`-of-base "flat" branch in `per_trade_verdict`, but it actually means "we have no
  history here," not "nothing happened."
- The two per-trade cards are **redundant mirror images** of each other.
- Color/arrow semantics encode raw value direction, not "good/bad for this owner": a
  given-away asset *losing* value is *good* for you but renders red/down.
- There is **no time axis** — no years, weeks, or season boundaries.

The cards answer the wrong question with the wrong data. They should answer: **while the
assets you received were on your team, how much did they actually produce — and did that
beat what you gave up?** That production data goes back to every trade's date; KTC value
does not.

## Goal

Replace both cards' KTC-value curves with **cumulative production timelines** on a real
calendar axis. KTC "Trade Value" stays unchanged everywhere else (the stat-table VALUE
column, the headline `snapshot_value_swing`); it is simply no longer the "did it pan out"
chart.

## Data availability (confirmed)

Everything this needs is already fetched and cached for every season in the league chain:

- **Weekly per-player points** — `MatchupResult.players_points` (`{player_id: points}`)
  per `(league_id, week, roster_id)`, cached with ~1-year TTL for historical seasons.
- **Started vs benched** per week — `starters` vs `players` lists on each roster-week.
- **Phase per week** — `engine/playoff_phase.py::classify_playoff_phases` →
  `(week, roster_id) → "playoff" | "toilet"`; weeks before `playoff_week_start` are
  "regular"; absent post-start weeks are "dropped"/bye.
- **Tenure window + terminal assets** — `engine/lineage.py::side_value_tenures` resolves a
  haul to its terminal assets (received pick → the player it was drafted into; a player
  flipped onward → terminal at the flip; held/dropped) with ISO terminal dates.

The only thing missing is a **materialized per-week production series** — a trivial new
aggregation over the same data `_points_while_owned` (`engine/trade_grader.py`) already
walks (it sums per-week per-player points away; we keep the per-week values instead).

## Design

### 1. Engine — production series (analog of value series)

New module `src/sleeper_dynasty/engine/production_series.py`, mirroring `value_series.py`:

- Reuse `side_value_tenures()` to resolve a haul (received or given) to terminal
  `AssetTenure` objects — identical lineage walk to the value series.
- Where `value_series` feeds tenures a **KTC price** function, the production series feeds
  them a **"points scored that week"** function: for terminal player `pid` on owner `uid`,
  look up `players_points[pid]` for each `(league_id, week, roster_id)` in the tenure
  window, gated by phase + started/bench exactly as `_points_while_owned` does.
- Output per side: a **cumulative** series `[(date, points_so_far)]` aligned to the
  weekly calendar, plus the per-asset sub-series for the drill.
- Cumulative mechanics: each scoring week steps the line up; benched weeks add nothing in
  started-only metrics; when an asset is flipped/dropped its sub-series **flattens at its
  terminal date** (you stopped owning it — consistent with the received-only "while on
  this side's roster" definition).
- Metric parameter selects which weeks/points count, matching the existing taxonomy:
  - **Total** — bench included, all weeks (default).
  - **Regular** — started-only, weeks `< playoff_week_start`.
  - **Playoff** — started-only, live title-path winners-bracket weeks.
  - **Toilet** — started-only, losers-bracket weeks.

Pure functions, fully unit-tested. KTC is not involved.

### 2. Engine — owner aggregate

Add an owner-level aggregate analog of `owner_value_series`: element-wise sum (via the
existing `sum_series` pattern, aligned on the shared weekly calendar) of the per-trade
production series across **all** of an owner's trades — received and given summed
separately. A trade contributes from its own trade date forward. Reuses the §1 primitive.

### 3. API

- **Per-trade** (`api/app/services/trade_view.py`): replace the per-trade
  `value_series` / `value_verdict` payload source with the production series. Response
  carries, per trade: both sides' cumulative series per metric, per-player sub-series, and
  the head-to-head verdict.
- **Owner** (owner deep-dive service): replace the aggregate `owner_value_series` /
  `aggregate_verdict` payload with the owner production aggregate — received vs given
  cumulative series per metric, per-trade sub-series, and the aggregate verdict.
- Computed + cached at refresh time on the `ChainCacheEntry`, alongside (or replacing) the
  current value-series payload in `grader.py::compute_value_series_payload`.
- New/updated response models in `api/app/models/trade.py` and the owner models.

### 4. Verdict reframing

Replace `per_trade_verdict` and `aggregate_verdict` (currently KTC-change + `<5%` "flat"
branch) with **production-margin** verdicts on the selected metric:

- **Per-trade (head-to-head):** compare final cumulative totals of the two hauls, e.g.
  *"Tom won the production battle, 900–705 total points."* Thresholds: blowout / clear /
  close / dead-even. Because the verdict is per metric, **a trade can pan out differently
  by metric** (even on total but won the playoff battle) — surfaced explicitly.
- **Owner aggregate:** margin + trend, e.g. *"Across 7 trades, your hauls have produced
  +312 total points more than what you shipped out."*
- **"Too early" state:** for trades with fewer than `N` post-trade games of data, show an
  honest "too early to tell" instead of a false "Boring."

### 5. Frontend

**Per-trade** — replace `TradeValueProgress.tsx` (and its two mirrored cards) with a
single `TradeProductionTimeline.tsx`:

- One combined chart per trade: both hauls as cumulative lines on a **real calendar
  x-axis** with **season-boundary gridlines + week ticks**, and **flip/drop markers**
  where a sub-asset's line flattens.
- Toggle: **both | side A only | side B only**. Isolating a side reveals its **per-player
  sub-lines** (aggregate + drill).
- Metric switcher: **Total | Regular | Playoff | Toilet** — re-accumulates the lines.
- Verdict line (§4), keyed to the selected metric.
- Steep segments read as hot streaks, flat as cold/injured/benched — the "when did they
  perform" signal.

**Owner aggregate** — rework `ValueProgressionCard.tsx`:

- One combined chart: this owner's **total received** vs **total given-away** cumulative
  production across all trades. Toggle: **both | what you got | what you gave up**.
- Drill: aggregate + **per-trade** sub-lines.
- Same metric switcher and calendar axis (spanning the owner's earliest trade → now).
- Aggregate verdict (§4).

### 6. Edge cases

- **3+ team trades:** N haul lines on the combined chart; verdict is pairwise/ranked.
- **Offseason:** chart works unchanged — it plots historical production, not live KTC, so
  the flat-line/"Boring" offseason failure disappears.
- **Picks before they're drafted:** contribute 0 until the terminal player exists, then
  the line begins stepping.
- **Benched weeks:** count in Total, excluded from Regular/Playoff/Toilet by definition.
- **Held asset still on roster:** line continues to "now."

### 7. Testing

- **Engine:** unit tests for the production-series primitive (held / flipped / dropped,
  pick→player resolution, phase gating, started-vs-bench, multi-season accumulation) and
  the owner aggregate (sum across trades, calendar alignment).
- **API:** series + verdict assembly for per-trade and owner.
- **Frontend:** render, toggle, metric switch, drill, and empty / too-early states.

## Out of scope (Phase 1)

- A positional/replacement **baseline** to judge "good vs bad" week-by-week (the chart
  shows raw cumulative production; "well" is read from slope and the head-to-head margin).
- Changes to the KTC "Trade Value" metric, the stat table, or the became-grade.
- **Injury context** — deferred to Phase 2 (below).

## Phase 2 — historical injury context (separate spec)

Decided in brainstorming (2026-06-24): injury annotation IS wanted, at full historical
fidelity (per-week injury status, total injury days, estimated points lost). This cannot
be reconstructed from current data — Sleeper's players dump is a current-only snapshot and
the matchup data has no DNP signal. It is therefore a **separate sub-project**, sequenced
after Phase 1 (the production timeline does not depend on it).

Direction agreed:
- **Data source: nflverse / `nfl_data_py`** (community parquet datasets) for historical
  weekly injury reports + active/inactive/DNP status + weekly stats — preferred over
  scraping PFR (clean dependency, no ToS gray area). To be confirmed in the Phase 2
  brainstorm.
- **Estimated points lost** requires a *healthy baseline* model (e.g. trailing healthy
  per-game average) — its own estimator with explicit design.
- **Rendering** on the timeline (injury markers vs a separate "lost to injury" tally) —
  to be designed in Phase 2.

Phase 2 gets its own brainstorm → spec → plan. Supersedes the `injury-acknowledgement-v2`
memory.

## Cleanup

The per-trade `value_series` data path and `engine/value_series.py` were built for these
cards. Once superseded, decide during planning whether to remove them or retain any part
still used elsewhere (verify no other consumer before deleting).

## Open questions

- Exact `N` for the "too early" threshold (number of post-trade games).
- Whether the metric switcher's default (Total) should be remembered per session.
