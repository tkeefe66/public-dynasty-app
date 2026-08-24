# Draft Results — Totals Row, All-Time View, Roster Status + Games Started

**Date:** 2026-06-27
**Area:** Owner/Franchise page → Outlook tab → "How past picks panned out" table
**Status:** Design approved; implementation deferred (another agent active in repo)

## Problem

The draft-results table on the Outlook tab (`web/components/ownerdeepdive/PastPicksTable.tsx`)
lists drafted picks per season with value-arc and production columns, but:

1. There is no per-table **totals row**, so a draft class can't be read at a glance.
2. There is no **All-Time** view — you can only inspect one season at a time.
3. There is no indication of whether a drafted player is **still on the owner's team**,
   nor how much the owner actually **started** them.

## Current state (for grounding)

- **Component:** `PastPicksTable.tsx` renders rows grouped by season with a year selector;
  `FutureDraftTab.tsx` owns the section and computes an all-time verdict sentence.
- **Model:** `DraftPickResult` (`api/app/models/owner.py:98-114`) — metadata + value arc
  (`current_value`, `lowest_value`, `highest_value`, `avg_slot_value`) + four production
  metrics (`production_total/regular/playoff/toilet`).
- **API assembly:** `api/app/services/owner_view.py:217-239` filters `entry.drafted_picks`
  by `drafter_id`, groups into `Record<str(season), DraftPickResult[]>`, sorts each season
  by `current_value - avg_slot_value`.
- **Engine:** `engine/draft_results.py::build_drafted_pick_results()` builds each pick dict;
  `started_points_while_on_roster()` (same file) owner-gates production — points only count
  while the player was on the drafting owner's roster.
- **No** stored "still on roster" flag and **no** games-started count exist today.
- **Cache:** `ChainCacheEntry.drafted_picks` is `list[dict]` (`chain_cache.py:67`), populated
  during refresh.

## Decisions (confirmed)

- Roster presence is shown as **two distinct facts**: a status chip (current standing) **and**
  a games-started count (historical). One does not imply the other.
- Games started is **one combined number** across all phases (regular + playoff + toilet).
- Totals row sums **every numeric column**, value columns included as-is.
- All-Time is an **extra entry in the year selector**, listing every pick (not a per-season summary);
  per-season tabs remain.

## Design

### New per-pick fields

Add to `DraftPickResult` (and the underlying `drafted_picks` dicts):

- `games_started: int` — count of weeks the player appeared in the drafting owner's **starting
  lineup** while on their roster, summed across all phases. One number.
- `roster_status: "rostered" | "traded" | "dropped"` — the player's **current** standing
  relative to the drafting owner.

### Engine (`engine/draft_results.py`)

- Add a count-counterpart to `started_points_while_on_roster()` — same owner-gated week loop,
  but counting starting-lineup appearances instead of summing points. Reuse the existing
  starters/roster-membership machinery so the gate matches production exactly.
- Derive `roster_status`:
  - `rostered` — player is on the drafting owner's roster at the latest week.
  - `traded` — player departed the owner's roster via a trade (departure event = trade).
  - `dropped` — player departed via a drop/waiver (departure event = drop).
  - Derive from the same latest-week roster membership + departure/lineage events already used
    elsewhere; confirm the exact source (`departures` / `roster_to_user_by_league`) during
    implementation and keep the logic pure + unit-testable.
- `build_drafted_pick_results()` populates both new keys per pick.

### API (`api/app/models/owner.py`, `api/app/services/owner_view.py`)

- Add `games_started: int` and `roster_status: str` to `DraftPickResult`.
- `owner_view.py` reads both from the pick dict with safe defaults
  (`games_started=0`, `roster_status="rostered"`) for pre-feature caches, and passes them through.

### Cache

- `drafted_picks` dicts gain two keys; old entries read via `.get(..., default)`.
- Bump `SCHEMA_VERSION` so a refresh recomputes drafted picks with the new fields
  (per the prod stale-cache gotcha). Run `next build` before deploy.

### Frontend (`PastPicksTable.tsx`, `FutureDraftTab.tsx`)

1. **Status chip column** — Rostered (positive token), Traded (neutral), Dropped (muted/negative).
2. **GS column** — `games_started`.
3. **Totals row** — pinned at the bottom of each rendered table; sums every numeric column
   (production, value-arc, GS) for the currently-shown rows.
4. **All-Time tab** — new sentinel entry (e.g. `"all"`) in the year selector. When active,
   render every pick flattened across seasons, sorted by the same `current_value - avg_slot_value`
   delta, with its own totals row. Per-season tabs unchanged.
5. Add `games_started` and `roster_status` to the `DraftPickResult` TS type.

## Testing

- Engine unit tests: games-started counter (owner-gated, multi-phase) and `roster_status`
  derivation (rostered / traded / dropped cases).
- Frontend test: totals-row sums and All-Time flattening/sort.

## Out of scope

- Per-phase games-started breakdown (one combined number only).
- Changing the existing value-arc or production semantics.
- Any change to future-pick arsenal or draft-needs sections.

## Notes

- Implementation deferred while another agent is active in the repo; this spec is written but
  **not committed** to avoid colliding with their git state.
