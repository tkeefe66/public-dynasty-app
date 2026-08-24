> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Outcomes-Dominant GM Rating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (Phases 1-3 are independent, well-specified backend tasks) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the single-blend GM Rating with a transparent three-pillar rating — `0.45·Outcomes + 0.30·TradeImpact + 0.25·Outlook` — where every rating point is traceable to a signal.

**Architecture:** Pure engine computes pillar z-scores from three per-owner signal sets and returns a full breakdown. Outcome signals (standings + brackets) and Outlook signals (dynasty: roster value / age / picks) are computed **during refresh** (where the raw data lives) and persisted on the `ChainCacheEntry`; Trade Impact signals already exist. The leaderboard service assembles the three sets and calls the new compute; the `/gm` UI renders the breakdown.

**Tech Stack:** Python (pytest, dataclasses, Pydantic v2, FastAPI), TypeScript/React (vitest, Tailwind).

**Spec:** `docs/superpowers/specs/2026-06-09-outcomes-dominant-gm-rating-design.md`

**Test commands:** engine `cd "<repo>" && .venv/bin/python -m pytest tests/ -q`; API `cd "<repo>/api" && .venv/bin/python -m pytest -q`; web `cd "<repo>/web" && npx vitest run --config tests/vitest.config.ts`. (`<repo>` = `/Users/tomkeefe/Code Apps/sleeper-dynasty`; use `git -C "<repo>"`.)

---

# PHASE 1 — Engine (pure, the core)

## Task 1: Three-pillar `compute_gm_ratings` + breakdown

**Files:** `src/sleeper_dynasty/engine/gm_rating.py` (rewrite), test `tests/test_gm_rating.py`.

Define the constants and a pure pipeline:

```python
PILLAR_WEIGHTS = {"outcomes": 0.45, "trade_impact": 0.30, "outlook": 0.25}
OUTCOME_WEIGHTS = {"championships": 0.35, "playoff_depth": 0.25,
                   "made_playoffs": 0.15, "final_seed": 0.15, "points_for_rank": 0.10}
TRADE_WEIGHTS  = {"playoff": 0.40, "regular": 0.30, "value": 0.22, "toilet": 0.08}
OUTLOOK_WEIGHTS = {"roster_value": 0.40, "draft_capital": 0.35, "youth": 0.25}
BASE, SCALE, CLAMP = 1500, 275, (800, 2200)
```

`compute_gm_ratings(owners)` where `owners[uid] = {"outcomes": {...}, "trade_impact": {...},
"outlook": {...}}` (each inner dict maps the pillar's signal keys → raw owner value). For each
pillar: z-score each signal across the league (population sd, the existing `_stats` helper),
blend by the pillar's weights → pillar z; blend pillars by `PILLAR_WEIGHTS` → composite z;
`rating = clamp(round(BASE + SCALE·composite_z))`. Return per uid:

```python
{"rating": int,
 "pillars": {pillar: {"weight": w, "z": float, "contribution": int,
                      "signals": {sig: {"raw": float, "z": float, "weight": w2,
                                        "contribution": int}}}}}
```

where a signal's `contribution = round(SCALE · PILLAR_WEIGHTS[pillar] · OUTCOME_WEIGHTS[sig] · sig_z)`
and a pillar's `contribution = round(SCALE · PILLAR_WEIGHTS[pillar] · pillar_z)`. (Signal
contributions sum to the pillar contribution up to rounding; document the rounding.)

- [ ] **Step 1: Write the failing test** — a 3-owner hand-computed fixture with known signal
  values per pillar. Assert: each pillar z, the composite, the final rating (BASE + SCALE·z
  clamped), and that `sum(signal.contribution) ≈ pillar.contribution` and
  `BASE + sum(pillar.contribution) ≈ rating` (within rounding). Also a single-owner / zero-sd
  case (z=0 → rating 1500) and the clamp.
- [ ] **Step 2: Run — expect fail.**
- [ ] **Step 3: Implement** the pipeline above (keep `_stats`; add pillar/blend logic + breakdown).
- [ ] **Step 4: Run engine suite green.** Note: `api/app/services/leaderboard.py::owner_metrics`
  currently passes a flat `{value,regular,playoff,toilet}` dict — it will be updated in Task 5;
  this task may temporarily break the leaderboard API tests, which Task 5 fixes.
- [ ] **Step 5: Commit** `feat(engine): three-pillar GM rating + full breakdown`.

## Task 2: `outcome_signals` extractor

**Files:** `src/sleeper_dynasty/engine/gm_signals.py` (new), test `tests/test_gm_signals.py`.

```python
def outcome_signals(
    *, standings_by_season: dict[int, list[StandingRow]],
    bracket_results_by_season: dict[int, dict],  # per-season finish info
    owners: list[str],
) -> dict[str, dict[str, float]]:
    """Per owner: {championships, playoff_depth, made_playoffs, final_seed, points_for_rank},
    aggregated across seasons. final_seed/points_for_rank are inverted so higher = better."""
```

- championships: count of seasons the owner won the title (winners-bracket final).
- playoff_depth: sum of rounds won (+ runner-up credit) across seasons.
- made_playoffs: count (or rate) of seasons reaching the playoffs (final seed ≤ num_playoff_teams).
- final_seed: average final regular-season rank, inverted (`total_rosters + 1 − rank`) so 1st is best.
- points_for_rank: average regular-season points-for rank, inverted likewise.

- [ ] **Step 1-4:** TDD with synthetic `StandingRow` lists + synthetic bracket-results dicts
  (a champion, a cellar-dweller, a perennial-playoff team). Assert the five signals per owner.
- [ ] **Step 5: Commit** `feat(engine): outcome-signal extractor (standings + brackets)`.

## Task 3: `outlook_signals` extractor

**Files:** `src/sleeper_dynasty/engine/gm_signals.py` (extend), test `tests/test_gm_signals.py`.

```python
def outlook_signals(
    *, outlooks_by_owner: dict[str, DynastyOutlook],   # from engine/dynasty.py
    roster_value_by_owner: dict[str, float],           # current KTC of the roster
) -> dict[str, dict[str, float]]:
    """Per owner: {roster_value, draft_capital, youth}. youth = -overall_avg_age (younger
    is better); draft_capital = DraftCapital.net_vs_average; roster_value = current KTC sum."""
```

- [ ] **Step 1-4:** TDD with synthetic `DynastyOutlook` (a pick-rich young team vs a pick-poor
  aging team) + roster-value map. Assert the three signals, youth sign (younger → higher).
- [ ] **Step 5: Commit** `feat(engine): outlook-signal extractor (dynasty analysis)`.

---

# PHASE 2 — Refresh enrichment (persist the signals)

## Task 4: Compute + persist outcome/outlook signals during refresh

**Files:** `api/app/services/grader.py` (or `grader_io.py` / a new `signals_io.py`), `api/app/services/chain_cache.py`, tests under `api/tests/`.

The signals need data assembled during refresh: standings (from the chain matchups, via
`engine/standings.py`), bracket results (from `winners_bracket`/`losers_bracket` in the matchup
bundle — already fetched in `grader_io::_league_matchup_bundle`), and dynasty inputs (current
rosters + KTC + player ages + owned picks).

- [ ] **Step 1:** Add `outcome_signals` and `outlook_signals` fields to `ChainCacheEntry`
  (`dict[str, dict[str, float]]`, default `{}`). Bump `SCHEMA_VERSION` (5 → 6) so refresh
  recomputes.
- [ ] **Step 2:** In the refresh/grader path (where `supporting` + brackets + KTC + players
  exist), per season: reconstruct final standings (`standings_as_of` through playoff start),
  derive bracket results (champion / rounds won) from the winners-bracket, and run
  `engine/dynasty.py` per owner for the **current** season (age profile + draft capital +
  window). Assemble `roster_value_by_owner` from `current_holders` × KTC. Call
  `outcome_signals(...)` and `outlook_signals(...)`; store both on the entry. Best-effort
  (wrap so refresh never fails on signal errors), mirroring `_snapshot_standings`.
- [ ] **Step 3:** Tests — a refresh produces non-empty `outcome_signals`/`outlook_signals` for
  a seeded chain; malformed inputs are swallowed.
- [ ] **Step 4: Commit** `feat(api): compute + persist outcome/outlook signals on refresh`.

---

# PHASE 3 — Leaderboard wiring

## Task 5: Assemble three pillars; expose breakdown

**Files:** `api/app/services/leaderboard.py`, `api/app/models/leaderboard.py`, tests.

- [ ] **Step 1:** Rewrite `owner_metrics` → `owner_pillars(rows, entry)` returning
  `{uid: {"outcomes": entry.outcome_signals[uid], "trade_impact": {value, regular, playoff,
  toilet}, "outlook": entry.outlook_signals[uid]}}` (trade_impact from the existing rollup).
  Handle owners missing outcome/outlook signals (default empty → z 0).
- [ ] **Step 2:** Feed `compute_gm_ratings(owner_pillars(...))`. Extend `GMRow` /
  `RatingBreakdown` (and `LeaderboardResp`) to carry the pillar subscores + full breakdown.
  Keep the sort by composite rating; keep `all_time_ratings` (snapshot payload) working
  against the new compute.
- [ ] **Step 3:** Update API tests (`test_leaderboard.py`, `test_refresh_rating_snapshot.py`)
  to the new pillar inputs + breakdown shape. Run API suite green.
- [ ] **Step 4: Commit** `feat(api): leaderboard builds three-pillar rating + breakdown`.

---

# PHASE 4 — Frontend

## Task 6: Pillar bars + transparency drill-down + explainer

**Files:** `web/lib/types.ts`, the `/gm` leaderboard components, the GM Rating explainer, tests.

- [ ] **Step 1:** Types for the breakdown (pillars → signals with raw/z/weight/contribution).
- [ ] **Step 2:** Leaderboard row shows the composite + three pillar contributions (e.g. a
  segmented bar or three small numbers). A per-owner **drill-down** (expand / detail panel)
  renders each pillar with its signals: raw value, league rank (z), and points contributed —
  reading like a receipt ("1,620 = 1500 +176 outcomes +72 trade +(−28) outlook"). Live mockup
  iteration for the breakdown layout.
- [ ] **Step 3:** Rewrite the GM Rating explainer copy for the three pillars + transparency.
- [ ] **Step 4:** Web tests for the breakdown rendering; `tsc` + vitest green.
- [ ] **Step 5: Commit** `feat(web): GM rating pillar breakdown + transparency drill-down`.

---

## Final verification
- [ ] Engine / API / web suites all green; `tsc` clean.
- [ ] Manual smoke: a real refresh populates the signals; `/gm` shows three pillars and a
      breakdown whose signal contributions sum (within rounding) to the rating.

## Self-review notes (addressed)
- **Pure core first:** the rating math + extractors (Phase 1) are pure and exhaustively
  tested before any plumbing.
- **Data plumbing isolated** to Phase 2 (refresh computes + persists signals; schema bump),
  so the leaderboard (Phase 3) just reads them.
- **Transparency is structural:** the engine returns the breakdown; the UI renders it.
- **Confounding avoided:** season-level outcomes + current outlook; no per-trade attribution.
- **Tunable:** all weights are constants.
- **Out of scope:** recency weighting, injuries, per-trade standings attribution.
