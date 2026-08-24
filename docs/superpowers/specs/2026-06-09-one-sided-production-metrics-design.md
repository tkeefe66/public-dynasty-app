# One-Sided Production Metrics (A-backend) — Design

**Date:** 2026-06-09
**Status:** Approved (brainstorm) → ready for implementation plan
**Part of:** Thread A of the owner/season-analyzer reshape. This is **A-backend**;
the visual presentation is **A-frontend** (separate, uses `frontend-design`).

## Context & motivation

The five-metric trade grade computes every metric as a **swing** (`received − given`),
where the `given` side is a *phantom* — the points a traded-away player scored,
counted against you. For **Trade Value** that's correct (it's a genuine zero-sum
exchange). But for the **bracket-phase production metrics** (Total / Regular / Playoff /
Toilet) the phantom is a category error: a traded-away player's bracket phase is the
**receiving team's** fate, not yours. So scoring points in *another team's* toilet bowl
drags down *your* Toilet metric — in a season where *your* team might be in the
playoffs. (See the discussion that produced this: the phantom's playoff/toilet label is
the wrong team's bracket.)

**Decision (brainstormed + confirmed):** make all four production metrics
**received-only** (one-sided) — "what my haul actually produced in my own bracket
games." Only **Trade Value** stays a swing. This also makes the *direct* grade
consistent with the **became grade** (`engine/regrade.py`), which is already one-sided.

The engine already computes the received side correctly: `grade_hindsight_production`'s
`_received_points` counts a received player's points **only while on the acquiring
roster**, tagged with **that (your) roster's** bracket phase. The fix is simply to
**drop the `given`/phantom term**.

## Scope boundary

**A-backend (this spec):** engine semantics + field rename through engine → cache →
GM Rating → API response models, plus the **mechanical** web field renames required to
keep the app compiling and tests green (no layout/visual changes). The app keeps
rendering; only the *values* (and field names) change.

**A-frontend (separate, next):** the trade-card / leaderboard visual redesign — present
production as head-to-head tallies ("104 vs 56") with a coherent treatment of the
mixed card (Trade Value is still a diverging swing; the four production metrics are two
independent positive tallies). Done with `frontend-design` + live mockups.

**Out of scope (deferred to B):** the **toilet sign / weight in GM Rating** (neutral vs.
negative) and the **outcomes-dominant** GM-Rating redesign. A-backend leaves
`gm_rating.WEIGHTS` untouched; it only changes *which values* feed the existing weights
(swings → received-only totals), since you chose "GM Rating uses the new values now."

## Key decisions (from brainstorm)

1. **All production one-sided; only Trade Value stays a swing.**
2. **Rename fields to received-only semantics** (names must stop saying "swing").
3. **GM Rating uses the new received-only values immediately** (interim board shift is
   acceptable; B reworks it). Toilet weight unchanged in A.
4. **Cache self-heals** via `SCHEMA_VERSION` bump (2 → 3) — forces a one-time re-grade.
5. **Non-breaking web:** A-backend includes the mechanical web rename so the app stays
   green; the visual redesign is A-frontend.

## Naming convention

Mirror the became grade's vocabulary so direct and became share one metric language.

| Concept | Nature | Engine `TradeGrade` (per-uid) | Engine `OwnerTradeRecord` (rollup) | API `TradeSideView` |
| --- | --- | --- | --- | --- |
| Trade Value | swing | `snapshot_value_swing` *(keep)* | `net_ktc` *(keep)* | `snapshot_ktc_swing` *(keep)* |
| Total Points | received-only | `production_total` | `production_total` | `production_total` |
| Regular Season | received-only | `production_started_regular` | `production_started_regular` | `production_regular` |
| Playoff | received-only | `production_started_playoff` | `production_started_playoff` | `production_playoff` |
| Toilet Bowl | received-only | `production_started_toilet` | `production_started_toilet` | `production_toilet` |

(Renamed from `hindsight_production_swing` / `hindsight_started_*_swing` /
`net_production*`.) The user-facing **labels** (Trade Value / Total Points / Regular
Season Points / Playoff Points / Toilet Bowl Points) are unchanged.

## Components & changes

### 1. Engine — `engine/trade_grader.py`
- `grade_hindsight_production`: drop the `given`/`_phantom_points` term — return
  per-uid **received-only** totals (`swings[uid] = received`). Remove/retire
  `_phantom_points` (or leave unused → delete to avoid dead code). Update the docstring
  ("received-only production; no phantom subtraction").
- `grade_trade`: rename the `TradeGrade` fields it populates (per the table).
  `grade_snapshot_value` is untouched (still a swing).
- `aggregate_owner_records`: rename the `OwnerTradeRecord` rollup fields; they sum the
  per-trade received-only values (a sum of received-only is still received-only).
- `models/trade.py`: rename `TradeGrade` + `OwnerTradeRecord` fields (the table).

### 2. Engine consumers
- `engine/trade_story.py` and `models/trade_story.py`: update any references to the
  renamed grade fields (grounded-facts for the LLM story).
- `output/google_sheets.py`: rename the columns/keys it reads.

### 3. Cache — `api/app/services/chain_cache.py`
- Bump `SCHEMA_VERSION` 2 → 3. The existing stale-schema check re-grades on read, so
  cached entries with old keys are discarded and rebuilt with received-only values.

### 4. GM Rating — `api/app/services/leaderboard.py`
- `owner_metrics` maps the renamed rollup fields into `compute_gm_ratings`:
  `value=net_ktc` (unchanged), `regular=production_started_regular`,
  `playoff=production_started_playoff`, `toilet=production_started_toilet`.
- `gm_rating.py` itself is **unchanged** (weights, scaling). The inputs are now
  received-only totals instead of net swings.
- Update other reads in this service (the `net_regular`/`net_playoff`/`net_toilet`
  response fields → renamed) consistently.

### 5. API response models + services
- `api/app/models/trade.py` (`TradeSideView`), `api/app/services/trade_view.py`:
  rename the four production fields (table); read the renamed engine grade keys.
- `api/app/services/aggregations.py`: rename rollup dict keys
  (`net_production*` → `production_*`) in `_aggregate_owner_rows` and downstream
  (`_records`, `_hero_stats`). `_letter_grade` keys off `net_ktc` — unchanged.
- `api/app/models/leaderboard.py`, `api/app/models/owner.py`,
  `api/app/services/owner_view.py`, `api/app/models/league.py`: rename the exposed
  production fields consistently.

### 6. Web — mechanical rename ONLY (keep green; no redesign)
- `web/lib/types.ts`: rename the field names on the response types.
- `web/components/TradeSidePanel.tsx`, `CareerArc.tsx`, `StandingsTable.tsx`,
  `web/lib/og-card-data.ts`, `web/lib/standings-filter.ts`, `web/lib/url-state.ts`:
  update field references so they compile and render. **No layout/visual change** —
  components keep their current shape; only the field names (and the values flowing
  through) change. Any visual oddness from received-only values in swing-shaped UI is
  acceptable interim and is fixed in A-frontend.
- Update the affected web tests mechanically (field names / expected values).

## Testing

- **Engine** (`tests/test_trade_grader.py`): add/adjust tests asserting production
  metrics are now received-only — specifically a case where a traded-away player scores
  in the *other* team's toilet bowl and confirm it **no longer** affects the trader's
  Toilet metric (the bug that motivated this). Confirm Trade Value still nets to zero
  across a two-party trade.
- **GM Rating** (`tests/test_gm_rating.py`): unchanged function; update the
  leaderboard-service test (`api/tests/test_leaderboard.py`) to feed received-only
  values.
- **API** (`api/tests/`): update `test_aggregations`, `test_trade`, `test_owner`,
  `test_models`, `test_leaderboard`, `test_grader_service`, `test_chain_cache`,
  `test_story_gen`, `test_refresh_rating_snapshot` for the renamed fields.
- **Web** (`web/tests/`): mechanical field/expectation updates so the suite passes.
- Full suites green: `pytest tests/`, `cd api && pytest`, `cd web && npm test`.

## Migration / rollout

- Cache bump forces a re-grade on next read; the cold-start contract already handles a
  cold cache (409 → `/refresh`). No data migration needed.
- This changes the GM leaderboard numbers (received-only inputs). Expected and accepted;
  B will redesign the rating shortly.

## Open questions

None blocking. The toilet sign and the outcomes-dominant rating are explicitly B's.
The only judgment call — keeping API field names honest vs. minimal web churn — is
resolved: rename through to the API and do the mechanical web rename now (chosen:
"rename to received-only semantics").
