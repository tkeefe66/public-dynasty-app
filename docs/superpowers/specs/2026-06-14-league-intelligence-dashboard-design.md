# League Intelligence Dashboard — Design Spec

**Date:** 2026-06-14  
**Status:** Approved  
**Sub-project:** B of 3 (see Franchise Command Center spec for full decomposition)

## Goal

Reframe the landing Dashboard tab from "trade highlights" to **league-wide competitive intelligence**. The page should answer "who's running the best franchise right now?" rather than "who won the best trade?". Trade data stays visible but becomes one column among several, not the organizing principle.

## What Changes

The Dashboard tab (`initialTab === "dashboard"` in `DashboardClient`) gets a full replacement of its two content sections:

1. **4 KPI hero cards** — replace the trade-highlight cards (Biggest Win, Best Pickup, Most Active, Activity) with 4 GM-intelligence spotlights.
2. **Standings table** — add GM Rating, Window, and Draft Capital columns; rename to "Owner Rankings"; change default sort to GM Rating.

Section header text changes from "Trade highlights [year]" to **"League Intelligence"**.

## KPI Cards

Four cards, same grid layout as today (`grid-cols-2 lg:grid-cols-4`):

| Label | Headline | Value | Footer |
|---|---|---|---|
| **Top GM** | Owner name | GM Rating (integer) | "GM Rating" |
| **Biggest Weekly Rise** | Owner name | ▲N (positions gained) | "GM Rating positions gained" |
| **Best Roster** | Owner name | KTC roster value (integer) | "KTC roster value" |
| **Draft Ace** | Owner name | Draft skill score (2 decimal places) | "draft skill score" |

**Sourcing rules:**
- **Top GM** — owner with the highest computed GM Rating this scope.
- **Biggest Weekly Rise** — owner with the highest positive `prev_rank − rank` delta (same `trend` field used by the GM leaderboard). Falls back to "—" / no owner when no prior week snapshot exists (first-ever refresh, offseason cold start).
- **Best Roster** — owner with the highest `outlook_signals["roster_value"]` raw value (KTC sum of current roster).
- **Draft Ace** — owner with the highest `outlook_signals["draft_skill"]` raw value. Falls back to "—" when no owner has a non-zero draft skill (e.g., startup-only leagues).

Cards link to the owner's detail page (`/league/{id}/owner/{uid}`) on click.

## Owner Rankings Table

**Columns (left → right):**

`# · Owner · GM Rating · Window · Draft Capital · Trade Value · Reg Pts · Playoff Pts · Grade`

**Column details:**

| Column | Source | Year-scoped? | Notes |
|---|---|---|---|
| `#` | `StandingRow.gm_rank` | No | Stable GM rank; does not change when user sorts by other columns |
| Owner | `StandingRow.owner` | — | Links to owner page |
| GM Rating | `StandingRow.gm_rating` | No | All-time composite; colored accent |
| Window | `StandingRow.window` | No | Color-coded pill: green=Contending, blue=Building, red=Rebuilding |
| Draft Capital | `StandingRow.draft_capital_value` | No | Raw KTC value of held future picks |
| Trade Value | `StandingRow.net_ktc` | Yes | Responds to year tab |
| Reg Pts | `StandingRow.production_regular` | Yes | Responds to year tab |
| Playoff Pts | `StandingRow.production_playoff` | Yes | Responds to year tab |
| Grade | `StandingRow.grade` | Yes | Letter grade pill |

**Default sort:** GM Rating descending. All columns remain sortable by click (existing sort behavior).

**Year filter note (rendered as a table footer):** "GM Rating · Window · Draft Capital are current-state and not affected by the year filter."

**Table title:** "Owner Rankings" (was "Owner Standings").

## Architecture

### Approach: Enrich `StandingRow` (Option A)

All new fields come from data already computed and cached in `ChainCacheEntry` during refresh. No new engine compute required at request time.

**New fields on `StandingRow`:**
```python
gm_rating: int | None = None       # computed via compute_gm_ratings()
gm_rank: int | None = None         # rank within this scope's rating list
gm_trend: int = 0                  # prev_rank − rank (positive = climbed)
window: str | None = None          # from dynasty_outlooks[uid]["window"]
draft_capital_value: float = 0.0   # from outlook_signals[uid]["draft_capital"]
```

**New fields on `HeroStats`** (replacing old trade-spotlight fields):
```python
top_gm: HeroStat
biggest_weekly_rise: HeroStat
best_roster: HeroStat
draft_ace: HeroStat
```

The old `HeroStats` fields (`biggest_win`, `best_pickup`, `most_active`, `activity`) are removed. `HeroStat` model shape is unchanged — `value` carries the number, `owner` the name, `owner_user_id` the link target, `context` the footer text.

**`build_dashboard()` changes:**
- Accepts an additional `prev_ratings: dict[str, int]` param (uid → prior rating, same as leaderboard route).
- GM ratings are always computed all-time: reuse `all_time_ratings(entry)` from `leaderboard.py` (internally calls `_aggregate_owner_rows` with `year="all"`, independent of the `year` param passed to `build_dashboard`). `gm_rating` and `gm_rank` are therefore stable across year tab changes.
- Derives `gm_trend` from `prev_ratings` (same delta logic as `build_leaderboard()`).
- Reads `window` from `entry.dynasty_outlooks[uid].get("window")`.
- Reads `draft_capital_value` from `entry.outlook_signals[uid].get("draft_capital", 0)`.
- Computes all four hero stats from the same all-time rating + signal pass.
- The existing `rank` field on `StandingRow` stays as the net_ktc rank (backward-compat with `at_trade_standing`). New `gm_rank` field is the GM-rating rank shown in the `#` column.

**`GET /api/league/{id}` route changes:**
- Calls `_prev_ratings()` (same helper already in the leaderboard route) and passes result to `build_dashboard()`.

### Frontend

- `web/lib/types.ts` — add new fields to `StandingRow`; replace `HeroStats` shape.
- `web/components/HeroStatsRow.tsx` — replace 4 old cards with 4 new intelligence cards.
- `web/components/StandingsTable.tsx` — add GM Rating, Window, Draft Capital columns; change default sort key; rename title; add table footer note; color-code Window pill.
- `web/components/DashboardClient.tsx` — update section header ("League Intelligence") and subtitle.

No new API endpoints. No changes to the leaderboard route, GM tab, or any other tab.

## Non-Goals

- No Monte Carlo odds or playoff projections (Sub-project C).
- No changes to Trades, Owners, or GM tabs.
- No changes to the cold-start 409 / refresh SSE flow.
- No login / "pick your team" concept.
- The `ExplainerBanner` is untouched.
- The `Records` panel (if surfaced elsewhere) is untouched.

## Edge Cases

- **No prior week snapshot** (first refresh ever, or single-week history): `gm_trend` defaults to 0 for all owners; "Biggest Weekly Rise" card shows "—" with no owner link.
- **Owner has no outlook data** (e.g., only appeared in old seasons, no refresh with dynasty_outlooks): `window` is `null` — render as an empty cell, not a pill.
- **No draft skill** (startup-only league, no rookie drafts yet): `draft_ace` card shows "—".
- **Tied GM Ratings** (rare, all-zero scenario): stable sort by `user_id` as tiebreaker.
