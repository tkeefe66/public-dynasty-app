# Franchise Score Redesign — Design

**Date:** 2026-06-26
**Branch:** `franchise-score-redesign`
**Status:** Approved design — ready for implementation plan

## Problem

The current Franchise Rating (`engine/gm_rating.py`) is a three-pillar composite —
`0.45·Outcomes + 0.30·TradeImpact + 0.25·Outlook` — where each pillar is a weighted
blend of league-z-scored signals, scaled to a 1500-centered number and mapped to a
letter grade. The results feel wrong, and the structure is conceptually backwards.

The core problem is the **Trade Impact** pillar. It is built from *received-only
production volume* (playoff/regular/value/toilet points tallied on the assets a side
received). That design:

- **Rewards volume, not skill** — an active trader racks up received points regardless
  of whether the deals were lopsided wins or losses.
- **Punishes non-traders** — a draft-built franchise that rarely trades scores near-zero
  and is dragged down.
- **Double-counts Outcomes** — received production points overlap with the points-for
  already counted in Outcomes.

The deeper reframe: **a franchise is measured by what it *achieves*** (championships,
playoff appearances, strong regular seasons). Trade skill, draft skill, and lineup skill
are not separate trophies sitting next to results — they are the **engines that produce**
results. We measure them separately because (a) they reward good process and (b) results
are noisy in fantasy (schedule luck, one hot playoff week), so skill is the more stable
signal of underlying quality.

This is a **blend, reweighted and restructured** — not a change to the conceptual basis
(still results + skill + outlook) and not a move away from league-relative z-scoring.

## Conceptual model

Three pillars, cleanly separated by the question each answers. Today's signals are
scattered (draft skill lives in Outlook, trade is its own pillar, lineup is measured
nowhere); the redesign consolidates them.

| Pillar | Question it answers | Signals |
|---|---|---|
| **Results** | What has this franchise *achieved*? | championships, playoff depth, made-playoffs rate, final seed, points-for rank |
| **Skill** | How well does the owner *operate* it? | trade-value skill, trade-production skill, draft skill, **lineup skill (new)** |
| **Outlook** | Where is it *headed*? | roster value, draft capital, youth |

The existing scaling machinery is unchanged: each signal is z-scored across the league,
a pillar's z is the weighted sum of its signal z-scores, the composite is the weighted
sum of pillar z-scores, and `rating = clamp(BASE + SCALE · composite)` with `BASE=1500`,
`SCALE=275`, `CLAMP=(800, 2200)`. Letter bands (`rating_to_letter`, `LETTER_BANDS`) are
unchanged. **Only the signal/pillar tree changes**, keeping blast radius contained. The
full transparency breakdown (pillar → signal → {raw, z, weight, contribution}) is
preserved so the "Why this grade" UI keeps working.

## Signal changes

### 1. Trade skill replaces Trade Impact volume

The old `trade_impact` pillar (received-points tallies: `playoff`/`regular`/`value`/
`toilet`) is removed. Trade is now measured by **two zero-sum, per-trade signals,
averaged per owner** (not summed) — so skill is decoupled from volume:

- **`trade_value`** — market-value swing per trade (`snapshot_value_swing` / `net_ktc`,
  already computed per trade). "Did you win the deal on today's market value?"
- **`trade_production`** — on-field production head-to-head per trade: the points the
  received assets scored vs the points the given assets scored, over the time held
  (the `production_winner_user_id` / `production_outcome` facts already computed in
  `engine/trade_story.py`). "Did it pan out on the field?"

Both metrics are **zero-sum across the league**, so the league mean of per-trade swing
is ≈ 0. An owner who never trades has raw 0, which sits at ≈ the league mean → a
**neutral z-score**. This is the desired property: non-traders are neither rewarded nor
punished.

**Small-sample guard (tunable):** shrink each owner's per-trade average toward neutral by
a confidence factor `n / (n + k)` with `k = 2`, so a single lucky trade does not spike an
owner. Default on; `k` is a tunable constant.

These two signals live in the **Skill** pillar (see weights below). The previously-shown
received-only production stats (Total / Regular Season / Playoff / Toilet Points) **remain
as descriptive trade stats** on the trade detail page and owner Trades tab — they simply
stop feeding the franchise rating.

### 2. Lineup skill (new signal)

Per roster-week, compute optimal-lineup points minus actual-started points and roll up to
a per-owner **lineup efficiency** = `Σ actual_started / Σ optimal` across all weeks the
owner played (chain-wide). Higher = starts the right players more often.

This reuses existing, production-tested engine code:

- `engine/lineup.py::solve_optimal_lineup(roster_positions, players)` — optimal slot
  assignment (already used by the simulator and weekly recaps).
- `engine/recap.py::build_bench_regret(...)` — per-roster-week optimal vs actual.

All required data is already fetched and assembled: `MatchupResult.starters`,
`MatchupResult.players_points` (starters **and** bench), `League.roster_positions`, and
the `positions` player→position map in the refresh `supporting` bundle
(`api/app/services/grader_io.py`).

New work required:

1. A pure per-owner aggregator (sum optimal + sum actual across roster-weeks → efficiency).
   Lives in the engine alongside the other signal extractors. Unit-tested.
2. A new field on `ChainCacheEntry` to persist the per-owner lineup-skill signal
   (**schema migration — bump `SCHEMA_VERSION`; see cache-migration note below**).
3. Wiring into `api/app/services/rating_signals.py` (compute during refresh) and into the
   Skill pillar in `compute_gm_ratings`.

### 3. Draft skill moves into Skill

`draft_skill` (rookie picks vs slot tier, `engine/draft_signals.py::draft_skill`) is a
skill, not a forward-looking bet. It moves from the Outlook pillar into the Skill pillar.
The computation itself is untouched; only its pillar assignment and weight change. Outlook
keeps `roster_value`, `draft_capital`, and `youth`.

## Signal weights (within pillars)

Tunable; these are the v1 starting points.

```
Results (5 signals):     championships 0.35, playoff_depth 0.25, made_playoffs 0.15,
                         final_seed 0.15, points_for_rank 0.10
Skill (4 signals):       trade_value 0.25, trade_production 0.20, draft_skill 0.30,
                         lineup_skill 0.25      (trade total = 0.45)
Outlook (3 signals):     roster_value 0.45, draft_capital 0.30, youth 0.25
```

## Two models — build both, then decide

The two candidate structures differ **only** in the top-level pillar weights. Implement
the pillar weights as a **named config** (e.g. a dict keyed by model name) so both ratings
can be computed from the same signals:

- **Model 1 — Results-primary:** `Results 0.55 / Skill 0.30 / Outlook 0.15`
  (closest to "a franchise is measured on championships; skill creates them").
- **Model 2 — Two equal axes:** `Results 0.43 / Skill 0.43 / Outlook 0.14`
  (luck-corrected skill treated as co-equal with raw results).

### Decision mechanism

Deliver a **comparison script** (e.g. a CLI subcommand or a standalone script under the
engine/tools) that, for a given league chain, prints a table of **every owner's rating +
letter under Model 1, Model 2, and today's current rating, side by side**, sorted by
rating. This lets us eyeball face-validity against intuition and **lock one model before
any UI work**.

## Phasing

1. **Engine + comparison (this spec's first deliverable).**
   - New `lineup_skill` aggregator + unit tests.
   - New `trade_value` / `trade_production` per-owner trade-skill aggregators + unit tests.
   - Restructured pillar/signal tree in `gm_rating.py` (Results / Skill / Outlook) with
     named pillar-weight configs for Model 1 and Model 2.
   - `ChainCacheEntry` schema migration for the lineup-skill signal (+ any new persisted
     signal inputs); bump `SCHEMA_VERSION`.
   - Comparison script printing both models vs current per owner.
   - **Decision point:** review the table, pick Model 1 or Model 2.
2. **UI wiring (after the model is locked).**
   - Update the Overview "Why this grade" pillar/signal breakdown to the new tree
     (`OverviewTab.tsx`, diverging contribution bars).
   - Update the LLM pillar-highlight pipeline pillar keys (Outcomes→Results,
     TradeImpact→Skill) in the GM-blurb writer (`blurb_gen.BLURB_PROMPT_VERSION` bump to
     regenerate cached blurbs).
   - Verify the letter surfaces (standings, owners rail, owner hero, `/gm` leaderboard)
     still render — the letter machinery is unchanged, only the inputs differ.

## Blast radius / files touched

**Engine (`src/sleeper_dynasty/engine/`):**
- `gm_rating.py` — new pillar/signal tree, named pillar-weight configs (Model 1/2).
- `gm_signals.py` — `outcome_signals` stays (Results); add lineup + trade-skill extractors
  (or a new sibling module, e.g. `skill_signals.py`).
- `lineup.py`, `recap.py` — reused as-is for lineup efficiency.
- `draft_signals.py` — `draft_skill` reused as-is (re-homed into Skill pillar).

**API (`api/app/services/`):**
- `rating_signals.py` — compute the new Skill-pillar signals during refresh; stop feeding
  the old trade-impact volume signals.
- `chain_cache.py` — new persisted field(s); `SCHEMA_VERSION` bump.
- `grader.py` / `grader_io.py` — invoke the lineup aggregator over assembled matchups.

**Frontend (`web/`):** deferred to phase 2 (after model lock).

## Cache migration note

Adding a persisted field to `ChainCacheEntry` can 500 prod via stale on-disk cache. Per
project memory: bump `SCHEMA_VERSION` and run `next build` before deploying. Historical
seasons use effectively-infinite TTL, so a schema bump is required to force recompute.

## Testing

- Pure unit tests for every new aggregator (lineup efficiency, trade-value skill,
  trade-production skill) and for the restructured `compute_gm_ratings` (signal
  contributions sum to pillar contribution; `BASE` + pillar contributions sum to rating;
  non-trader lands neutral on trade signals).
- Comparison-script output reviewed manually for face validity (the decision gate).
- After phase 2: `next build` (catches `'use client'` / RSC issues) + Playwright smoke.

## Open / tunable parameters (not blockers)

- Pillar weights for each model (above) — starting points, tune after seeing the table.
- Within-pillar signal weights — starting points.
- Trade small-sample shrinkage constant `k` (default 2).
- Whether lineup efficiency is a simple ratio or weighted by games played — start simple
  (aggregate ratio across all weeks).
