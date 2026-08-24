# Bracket-Aware Playoff Grading & Production Phase Taxonomy — Design Spec

**Date:** 2026-06-08
**Status:** Design approved — pending spec review before plan.
**Owner:** Tom Keefe

## Problem

"Playoff Points" (`net_production_started_playoff`, the **0.40**-weighted term in the
GM Rating) is computed as *started points in any week ≥ the league's playoff-start
week*. That gate is purely a **calendar threshold** (`trade_grader.py`: `if
playoff_only and wk < playoff_weeks_by_league.get(lg, 15): return False`). It does
**not** check whether the owner's team actually made the playoff bracket.

Sleeper still produces `starters` + `players_points` for **every** team in weeks
15–17, including eliminated ones and teams that missed the playoffs entirely. So a
non-playoff team accrues "Playoff Points" for whatever its starters scored in those
weeks — and that pollutes the headline GM Rating signal.

The fix is to make playoff production **bracket-aware**: a started week only counts
as playoff production if the roster was actually playing a live, title-contending
game that week. While we're touching the production model, we also partition started
production into clean, non-overlapping phases (Regular Season / Playoff / Toilet Bowl)
so every production number reflects the kind of game the roster actually played.

## Data availability (verified against the real league)

Confirmed by hitting Sleeper's public API for league chain `9000000000000000001`
(2026 entry-point) and walking `previous_league_id`:

| Season | Status | total_rosters | playoff_teams | playoff_week_start | round_type | winners_bracket | losers_bracket |
|---|---|---|---|---|---|---|---|
| 2026 | in_season | 12 | 6 | 15 | 0 | 7 games (R1–3) | present |
| 2025 | complete | 12 | 6 | 15 | 0 | 7 games (R1–3) | 7 games (R1–3) |
| 2024 | complete | 12 | 6 | 15 | 0 | 7 games (R1–3) | 7 games (R1–3) |
| 2023 | complete | 12 | 6 | 15 | 0 | 7 games (R1–3) | 7 games (R1–3) |

Every team is in exactly one bracket in weeks 15–17 (6 winners + 6 losers), so the
phase partition is near-total. `playoff_round_type == 0` (one week per round) for all
seasons. The real `playoff_week_start` is already plumbed correctly
(`grader_io.py` uses the league setting, not a hardcoded 15).

**Real 2025 winners_bracket** (used for golden tests):

```
{"m":1,"r":1,"t1":6, "t2":12,"w":6, "l":12}            # QF  wk15
{"m":2,"r":1,"t1":2, "t2":5, "w":5, "l":2}             # QF  wk15
{"m":3,"r":2,"t1":1, "t2":6, "w":1, "l":6}             # SF  wk16 (roster 1 had R1 bye)
{"m":4,"r":2,"t1":10,"t2":5, "w":10,"l":5}             # SF  wk16 (roster 10 had R1 bye)
{"m":5,"p":5,"r":2,"t1":12,"t2":2, "w":12,"l":2}       # 5th-place wk16  -> DROPPED
{"m":6,"p":1,"r":3,"t1":1, "t2":10,"w":1, "l":10}      # CHAMP wk17
{"m":7,"p":3,"r":3,"t1":6, "t2":5, "w":5, "l":6}       # 3rd-place wk17  -> DROPPED
```

## Locked decisions (from brainstorming)

| # | Decision | Choice |
|---|---|---|
| 1 | Playoff gate | A started week counts as **Playoff Points** only if the roster played a **live title-path winners-bracket game** that week. |
| 2 | "Title-path" definition | A winners-bracket entry with **no `p` field, or `p == 1`** (championship). Placement games (`p >= 3`, i.e. 3rd/5th) are **not** title-path. |
| 3 | Byes | A bye week is **not** a game → **0** Playoff Points that week. |
| 4 | Elimination | Falls out automatically — an eliminated team simply doesn't appear in later title-path games, so later weeks contribute 0. |
| 5 | Symmetry | The "gave-away" (phantom) side uses the **same** title-path eligibility set as the "received" side. A player traded to a non-playoff team costs **0** playoff points. |
| 6 | New taxonomy | Partition started production into **Regular Season** / **Playoff** / **Toilet Bowl** (see below). |
| 7 | Toilet Bowl | Started points in **any losers-bracket game** (no title-path filtering — the whole losers bracket is "toilet bowl"). |
| 8 | Dropped buckets | Byes and winners-bracket **placement games** (3rd/5th) count toward **no** phase metric. |
| 9 | GM Rating weights | **Playoff 0.40 / Regular 0.30 / Trade Value 0.22 / Toilet Bowl 0.08** (sum 1.0). |
| 10 | Missing-bracket guard | If a bracket can't be resolved for a season → credit **0** for that phase + **log loudly**. Never silently wrong. (Not triggered by this league.) |
| 11 | Approach | **B** — isolate bracket interpretation in a pure `engine/playoff_phase.py` module. |
| 12 | became-grade | **In scope** — recompute its production with the same taxonomy, so direct grades and "became" grades share one playoff definition. |
| 13 | Validation | Golden unit tests + a written audit report (2023–25) + a live app check. |

## The metric taxonomy

Started-lineup points are classified **per (league, week, roster)** by the kind of
game the roster actually played that week:

| Metric | Internal field (per-owner) | Definition |
|---|---|---|
| **Trade Value** | `net_ktc` | KTC market-value swing (unchanged) |
| **Total Points** | `net_production` | all rostered incl. bench, all weeks (unchanged, informational) |
| **Regular Season Points** | `net_production_started_regular` | started, weeks `< playoff_week_start` |
| **Playoff Points** | `net_production_started_playoff` | started, **title-path winners-bracket games** |
| **Toilet Bowl Points** | `net_production_started_toilet` | started, **any losers-bracket game** |

Per-trade swing fields mirror this on `TradeGrade`:
`hindsight_started_regular_swing`, `hindsight_started_playoff_swing` (renamed-meaning),
`hindsight_started_toilet_swing`. The old `hindsight_started_swing` /
`net_production_started` (all-weeks started) is **removed** and replaced by the
`_regular` field; consumers that summed "started" now choose a phase.

**Reconciliation invariant:** for any owner,
`regular + playoff + toilet ≤ started_total_all_weeks`, with the remainder being
dropped weeks (byes + winners placement games). Tested.

**Consumers of the old all-weeks `net_production_started`:** every place that read it
(dashboard standings column, owner detail, records in `aggregations._records`, any
sort key) switches to **Regular Season Points** (`net_production_started_regular`).
There is intentionally **no** "all started weeks" combined metric surfaced; if one is
ever needed it is `regular + playoff + toilet` (excludes dropped weeks by design).

## Architecture (Approach B)

### Component 1 — `engine/playoff_phase.py` (new, pure)

```python
def classify_playoff_phases(
    winners_bracket: list[dict],
    losers_bracket: list[dict],
    playoff_week_start: int,
    playoff_round_type: int,
) -> dict[tuple[int, int], str]:
    """(week, roster_id) -> "playoff" | "toilet". Absent = dropped/regular.

    - round -> week: type 0 => week = playoff_week_start + r - 1.
      types 1 (2-week championship) / 2 (2-week rounds) get an explicit mapping.
    - playoff set: winners entries with no "p" or p == 1, concrete roster ids only.
    - toilet set: all losers entries, concrete roster ids only.
    - unresolved (null) roster slots during live play are skipped.
    """
```

Pure, no I/O, no Sleeper types — takes raw dicts + two ints. This is where the
edge-case rigor lives. Single responsibility: interpret brackets into a phase map.

**Runtime sanity guard:** when consumed, any `(week, roster)` whose week has no
matching matchup data is logged and dropped — an exotic/mis-mapped format fails safe
instead of mis-attributing points.

### Component 2 — Sleeper client (`api/sleeper.py`)

Add `get_winners_bracket(league_id)` and `get_losers_bracket(league_id)` →
`GET /league/{id}/winners_bracket` and `/losers_bracket`. Return raw list-of-dicts.
Best-effort: a fetch error returns `[]` (→ missing-bracket guard).

### Component 3 — `grader_io.py` / matchup bundle

`_league_matchup_bundle` fetches both brackets, stores them raw in the (cached)
bundle, and builds `phase_by_lwr: dict[(league_id, week, roster_id), str]` by calling
`classify_playoff_phases` per league. Brackets for `status == "complete"` seasons are
sealed/cached with the bundle (effectively-infinite TTL); the in-progress season
refetches each refresh (bracket fills in week by week — naturally handled, since only
resolved+played games appear).

### Component 4 — Grader (`engine/trade_grader.py`)

Replace the `playoff_only` calendar gate with a phase-aware computation:

```python
def grade_started_by_phase(
    rt, matchups, roster_to_user_by_league, phase_by_lwr,
    playoff_week_start_by_league, league_season_by_id=None,
) -> dict[str, dict[str, float]]:   # uid -> {"regular","playoff","toilet": swing}
```

For each started `(lg, wk, rid)`: `regular` if `wk < playoff_start[lg]`, else the
phase from `phase_by_lwr.get((lg, wk, rid))` (one of `playoff`/`toilet`/absent→drop).
Received and phantom sides both use this lookup. Total Points (bench-inclusive,
all weeks) remains a separate untouched calculation.

### Component 5 — GM Rating (`engine/gm_rating.py`)

```python
WEIGHTS = {"playoff": 0.40, "regular": 0.30, "value": 0.22, "toilet": 0.08}
```

`compute_gm_ratings` is otherwise unchanged (z-score per metric, scale, 1500-center,
clamp). Breakdown dict gains `regular` and `toilet` keys. `owner_metrics`
(`leaderboard.py`) maps owner rows → `{playoff, regular, value, toilet}`.

### Component 6 — Models / API surface

- `models/trade.py` `TradeGrade`: replace `hindsight_started_swing` with
  `hindsight_started_regular_swing`; add `hindsight_started_toilet_swing`.
- `models/lineage.py` (became): same three phase fields on the became grade.
- api `models/leaderboard.py` `RatingBreakdown`: add `regular`, `toilet`.
- api trade/owner response models: add `net_production_started_regular`,
  `net_production_started_toilet` (keep `net_production_started_playoff`); drop the
  old all-weeks `net_production_started`.
- `aggregations._aggregate_owner_rows`: accumulate the three phase buckets.
- `trade_view.py`: expose the three started phases on the trade detail.

### Component 7 — became-grade (`engine/lineage.py`)

`build_became_grade` recomputes terminal-player production through the same
`phase_by_lwr` map → "what it became" reports Regular/Playoff/Toilet identically to the
direct grade.

### Component 8 — Web (`web/`)

- `lib/types.ts`: `RatingBreakdown` gains `regular` + `toilet`; trade/owner metric
  shapes gain the phase fields.
- `components/Leaderboard.tsx`: breakdown rows = Base 1500 + Playoff + Regular +
  Trade Value + Toilet Bowl.
- trade detail + `components/TradeBecame.tsx`: render the three phase metrics.
- OG card (`lib/og-card*.ts(x)`): include the breakdown's new terms if shown.
- **Labels:** *Regular Season Points*, *Playoff Points*, *Toilet Bowl Points*
  (alongside *Trade Value*, *Total Points*). Update the "metrics vocabulary" in
  `README.md` + `CLAUDE.md` (four metrics → five).

## Migration / re-grade

Computation changes invalidate cached grades, and cached matchup bundles predate the
bracket fields. Bump a **cache schema version** so:
1. matchup bundles refetch (to pull `winners_bracket`/`losers_bracket`), and
2. the chain re-grades on next refresh.

Both the manual `/refresh` SSE and the auto-refresh scheduler pick this up. One-time
recompute; **every GM Rating will shift**. No user-facing migration step beyond the
next refresh completing.

## Error handling

- Bracket fetch failure / empty bracket / unresolvable round→week → that phase
  contributes 0 for the affected season + a **WARN** log naming league + season.
  Never falls back to the old calendar behavior (that would reintroduce the bug).
- Unresolved (null) roster slots in a live bracket are skipped (no premature credit).
- The phase classifier is pure and total — never raises on malformed entries; it skips
  what it can't interpret and the caller logs drops.

## Testing & validation

**Unit (engine, TDD-first):**
- `playoff_phase`: golden cases from the real 2025 winners+losers brackets — assert
  exact `(week, roster) → phase`, including bye rosters absent in wk15, 3rd/5th-place
  rosters absent in wk16–17, and all losers rosters → `toilet`. Synthetic cases for
  `playoff_round_type` 1 & 2, unresolved live entries, and empty brackets.
- `trade_grader.grade_started_by_phase`: synthetic matchups proving received +
  phantom symmetry and correct per-phase attribution.
- `gm_rating`: new weight vector + breakdown keys; sum-to-1 spread preserved.

**Integration (api):** leaderboard + trade detail expose the new fields; reconciliation
invariant (`regular + playoff + toilet ≤ started_total`); a non-playoff owner shows
`playoff == 0` and (if they traded) nonzero `toilet`.

**Audit report:** `scripts/audit_playoff_phases.py` (committed) — for the real league,
per season: bracket membership (who made winners vs losers), per-owner Regular/Playoff/
TB points, and assertions (each season's champion's acquired-and-started players show
playoff points; missed-playoff owners show 0 playoff). Human-readable; eyeballed
against what actually happened.

**Live check:** run the app; verify the GM tab breakdown and a couple of trade pages
render the five metrics sensibly.

**Confidence bar:** golden tests green + audit report matches reality + live render
correct ⇒ ≥95% confidence.

## Out of scope

- Changing **Total Points** (bench-inclusive) or **Trade Value**.
- Re-weighting beyond the agreed vector.
- Reworking the trade-story LLM prompts (they may reference the new labels later;
  not required here).
- Backfilling historical *rating snapshots* (trend) — they recompute forward naturally.

## Touched files (orientation, not exhaustive)

- New: `src/sleeper_dynasty/engine/playoff_phase.py`, `tests/test_playoff_phase.py`,
  `scripts/audit_playoff_phases.py`.
- Engine: `engine/trade_grader.py`, `engine/gm_rating.py`, `engine/lineage.py`,
  `models/trade.py`, `models/lineage.py`.
- API: `api/sleeper.py` (client), `app/services/grader_io.py`, `app/services/grader.py`,
  `app/services/aggregations.py`, `app/services/leaderboard.py`,
  `app/services/trade_view.py`, `app/services/chain_cache.py` (schema version),
  `app/models/leaderboard.py`, `app/models/trade.py`.
- Web: `web/lib/types.ts`, `web/components/Leaderboard.tsx`,
  `web/components/TradeBecame.tsx`, trade detail page, `web/lib/og-card*.ts(x)`.
- Docs: `README.md`, `CLAUDE.md`.
